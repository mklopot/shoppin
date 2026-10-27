"""
Shopping list views and HTMX controller endpoints.

Handles item CRUD operations, status transitions (NEED, GOT, HAVE, DONT_NEED),
item and section drag-and-drop reordering, store selection, and Pantry Check mode.
"""

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.categorizer import categorizer
from apps.core.services.workspace_service import get_active_workspace
from apps.core.utils import (
    can_combine_units,
    clean_purpose,
    combine_amounts_and_units,
    is_quantity_increased,
    parse_amount_and_unit,
    singularize,
)
from apps.shopping.models import (
    GroupBy,
    ItemStatus,
    ListMode,
    ShoppingList,
    ShoppingListItem,
    StoreItemAisle,
    StoreLocation,
)
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.list_organizer import ShoppingListOrganizer
from apps.shopping.services.preset_service import check_and_apply_due_preset_schedules
from apps.shopping.services.store_service import (
    get_known_aisles,
    get_known_categories,
    get_nearest_stores,
    resolve_store_aisle,
)


def get_active_list(request: HttpRequest | None = None) -> ShoppingList:
    """
    Retrieve or initialize the active shopping list for the current request's workspace.

    Args:
        request: Optional Django HttpRequest.

    Returns:
        The active primary ShoppingList instance for the workspace.
    """
    workspace = get_active_workspace(request)
    shopping_list = workspace.get_primary_list()
    if not shopping_list:
        # Check if an unassigned primary list exists (e.g. from fixtures or migrations)
        unassigned_list = ShoppingList.objects.filter(is_preset=False, workspace__isnull=True).first()
        if unassigned_list:
            unassigned_list.workspace = workspace
            unassigned_list.save(update_fields=["workspace"])
            return unassigned_list

        default_store = StoreLocation.objects.first()
        shopping_list = ShoppingList.objects.create(
            name=f"{workspace.name} Shopping List",
            workspace=workspace,
            owner=workspace.owner,
            is_preset=False,
            active_store=default_store,
        )
    return shopping_list


def _check_write_permission(request: HttpRequest, shopping_list: ShoppingList) -> HttpResponseForbidden | None:
    """
    Verify the user has edit/write permissions on the workspace.

    Args:
        request: Current HttpRequest.
        shopping_list: ShoppingList target.

    Returns:
        HttpResponseForbidden if read-only, otherwise None.
    """
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        workspace = shopping_list.workspace or get_active_workspace(request)
        if workspace and not workspace.can_write(user):
            return HttpResponseForbidden("You have read-only access to this workspace.")
    return None


def _build_list_context(
    request: HttpRequest | None,
    shopping_list: ShoppingList,
    group_by: GroupBy | str = GroupBy.CATEGORY,
    mode: ListMode | str | None = None,
) -> dict[str, Any]:
    """
    Construct the unified template context for rendering the shopping list.

    Delegates status partitioning and section sorting to ShoppingListOrganizer.

    Args:
        request: Current HttpRequest (optional).
        shopping_list: Target ShoppingList instance.
        group_by: Grouping key ('category' or 'aisle').
        mode: Shopping mode ('shopping' for In Store, or 'pantry' for Pantry Check).

    Returns:
        Context dictionary for HTML rendering.
    """
    active_mode = ShoppingListOrganizer.resolve_view_mode(request, mode)
    items = shopping_list.items.all().order_by("order", "id")

    need_items, got_items, pantry_items = ShoppingListOrganizer.partition_items(items)
    need_confirmed_count = sum(1 for item in need_items if item.locked)
    need_unconfirmed_count = len(need_items) - need_confirmed_count
    grouped_need = ShoppingListOrganizer.group_and_sort_need_items(
        need_items=need_items,
        group_by=group_by,
        shopping_list=shopping_list,
    )

    stores = StoreLocation.objects.all().order_by("name")
    known_categories = get_known_categories()
    known_aisles = get_known_aisles(shopping_list.active_store)

    workspace = shopping_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        can_write = workspace.can_write(user) if workspace else True
        user_role = workspace.get_user_role(user) if workspace else "owner"
    else:
        can_write = True
        user_role = "owner"

    meal_plan = workspace.get_meal_plan() if workspace else None
    planned_meals = list(meal_plan.meals.prefetch_related("recipes").all()) if meal_plan else []

    preset_lists = []
    if workspace:
        raw_presets = list(workspace.get_preset_lists().prefetch_related("items").order_by("name"))
        for p in raw_presets:
            p.loaded_items_count = shopping_list.items.filter(source_preset=p).count()
            p.is_loaded = p.loaded_items_count > 0
            preset_lists.append(p)

    preset_lists_open = request.COOKIES.get("preset_lists_open", "true") != "false"

    return {
        "shopping_list": shopping_list,
        "workspace": workspace,
        "planned_meals": planned_meals,
        "preset_lists": preset_lists,
        "preset_lists_open": preset_lists_open,
        "can_write": can_write,
        "user_role": user_role,
        "grouped_need": grouped_need,
        "need_count": len(need_items),
        "need_confirmed_count": need_confirmed_count,
        "need_unconfirmed_count": need_unconfirmed_count,
        "got_items": got_items,
        "got_count": len(got_items),
        "pantry_items": pantry_items,
        "pantry_count": len(pantry_items),
        "group_by": str(group_by),
        "stores": stores,
        "active_store": shopping_list.active_store,
        "known_categories": known_categories,
        "known_aisles": known_aisles,
        "mode": active_mode,
    }


def render_list_response(
    request: HttpRequest,
    context: dict[str, Any],
    toast_message: str | None = None,
    force_partial: bool = True,
) -> HttpResponse:
    """
    Render standardized HTTP responses for shopping list views.

    For action endpoints or HTMX swaps, renders the partial template
    'shopping/partials/list_content.html'. For direct browser navigations
    to the list view, renders the full 'shopping/list.html' page.

    Args:
        request: The current HttpRequest.
        context: Context dictionary containing shopping list data.
        toast_message: Optional notification message displayed to the user.
        force_partial: If True, always render the partial template.

    Returns:
        Rendered HttpResponse containing the partial or full page.
    """
    if toast_message:
        context["toast_message"] = toast_message

    target = request.headers.get("HX-Target", "").lstrip("#")
    if force_partial or (
        request.headers.get("HX-Request")
        and not request.headers.get("HX-Boosted")
        and (not target or target == "shopping-list-content")
    ):
        return render(request, "shopping/partials/list_content.html", context)

    return render(request, "shopping/list.html", context)


def shopping_list_view(request: HttpRequest) -> HttpResponse:
    """
    Render the main shopping list page, or return an HTMX partial replacement.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML page or HTMX partial content.
    """
    workspace = get_active_workspace(request)
    if workspace:
        check_and_apply_due_preset_schedules(workspace, request=request)

    shopping_list = get_active_list(request)
    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    mode = request.GET.get("mode")
    context = _build_list_context(request, shopping_list, group_by, mode=mode)
    return render_list_response(request, context, force_partial=False)


def pantry_check_view(request: HttpRequest) -> HttpResponse:
    """
    Render the shopping list in Pantry Check mode.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML page or HTMX partial content in Pantry Check mode.
    """
    workspace = get_active_workspace(request)
    if workspace:
        check_and_apply_due_preset_schedules(workspace, request=request)

    shopping_list = get_active_list(request)
    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, shopping_list, group_by, mode=ListMode.PANTRY)
    return render_list_response(request, context, force_partial=False)


def _set_item_audit(item: ShoppingListItem, request: HttpRequest) -> None:
    """
    Record user attribution and timestamp metadata on an item during state changes.

    Sets status_changed_by to the authenticated user or None, and status_changed_by_name
    to the username or 'unknown' for anonymous interactions. Never sets 'You'.

    Args:
        item: The ShoppingListItem instance being updated.
        request: The current HTTP request.
    """
    item.status_changed_at = timezone.now()
    if request.user.is_authenticated:
        item.status_changed_by = request.user
        item.status_changed_by_name = request.user.username
    else:
        item.status_changed_by = None
        item.status_changed_by_name = "unknown"


def _get_client_id(request: HttpRequest) -> str:
    """Extract unique client tab identifier from headers or META."""
    return request.headers.get("X-Client-Id") or request.META.get("HTTP_X_CLIENT_ID") or ""


@require_POST
def set_item_status(request: HttpRequest, item_id: int, new_status: str) -> HttpResponse:
    """
    Transition an item to a new status (NEED, GOT, HAVE, DONT_NEED).

    Updates audit metadata and returns the re-rendered list partial with a toast message.

    Args:
        request: The POST request.
        item_id: Primary key of the item.
        new_status: Target status code string.

    Returns:
        Rendered HTML partial with updated list and toast notification.
    """
    item = get_object_or_404(ShoppingListItem, id=item_id)
    forbidden = _check_write_permission(request, item.shopping_list)
    if forbidden:
        return forbidden

    if new_status in ItemStatus.values:
        item.status = new_status
        if new_status == ItemStatus.NEED:
            item.locked = True
        _set_item_audit(item, request)
        item.save(
            update_fields=[
                "status",
                "locked",
                "status_changed_at",
                "status_changed_by",
                "status_changed_by_name",
                "updated_at",
            ]
        )

    shopping_list = item.shopping_list
    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, shopping_list, group_by)

    status_messages = {
        ItemStatus.GOT: f"🛒 You moved '{item.name}' to Cart",
        ItemStatus.HAVE: f"🏠 You marked '{item.name}' as Already in Pantry",
        ItemStatus.DONT_NEED: f"⏭ You skipped '{item.name}'",
        ItemStatus.NEED: f"📋 You moved '{item.name}' back to To Buy",
    }
    toast = status_messages.get(new_status, f"You updated '{item.name}'")

    other_status_messages = {
        ItemStatus.GOT: f"🛒 {item.changed_by_display} moved '{item.name}' to Cart",
        ItemStatus.HAVE: f"🏠 {item.changed_by_display} marked '{item.name}' as in Pantry",
        ItemStatus.DONT_NEED: f"⏭ {item.changed_by_display} skipped '{item.name}'",
        ItemStatus.NEED: f"📋 {item.changed_by_display} moved '{item.name}' back to To Buy",
    }
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=other_status_messages.get(new_status, f"{item.changed_by_display} updated '{item.name}'"),
        actor_name=item.changed_by_display,
        sender_client_id=_get_client_id(request),
    )
    return render_list_response(request, context, toast_message=toast)


@require_POST
def add_item(request: HttpRequest) -> HttpResponse:
    """
    Add a new item to the active shopping list or increment quantity of an existing one.

    Predicts the department category and resolves the store aisle if a store is active.

    Args:
        request: The POST request containing name, amount, brand, vendor, aisle, purpose.

    Returns:
        Rendered HTML partial or redirect.
    """
    shopping_list = get_active_list(request)
    forbidden = _check_write_permission(request, shopping_list)
    if forbidden:
        return forbidden

    raw_name = request.POST.get("name", "").strip()
    if not raw_name:
        return redirect("shopping:list")

    priority_flag = request.POST.get("priority") in ("true", "1", "on", True)
    for trigger in ("🚩", "!", "^"):
        if trigger in raw_name:
            priority_flag = True
            raw_name = raw_name.replace(trigger, "").strip()

    raw_amount = request.POST.get("amount", "1")
    amount, amount_unit = parse_amount_and_unit(raw_amount)
    brand = request.POST.get("brand", "").strip()
    vendor = request.POST.get("vendor", "").strip()
    purpose = clean_purpose(request.POST.get("purpose", "").strip()) or "one-time purchase"

    # Category: use user-provided value or infer via categorizer
    raw_category = request.POST.get("category", "").strip()
    category = raw_category or categorizer.get_category(raw_name)

    # Aisle: use user-provided value or resolve via store service
    raw_aisle = request.POST.get("aisle", "").strip()
    if raw_aisle:
        aisle = raw_aisle
    elif shopping_list.active_store:
        aisle_info = resolve_store_aisle(shopping_list.active_store, raw_name)
        aisle = aisle_info.get("aisle_name", "")
    else:
        aisle = ""

    # Check for deduplication / stacking with an existing NEED item
    normalized_name = singularize(raw_name.lower())

    existing: ShoppingListItem | None = None
    for candidate in shopping_list.items.filter(status=ItemStatus.NEED):
        if (
            singularize(candidate.name.lower()) == normalized_name
            and can_combine_units(candidate.amount_unit, amount_unit)
            and candidate.brand.lower() == brand.lower()
            and candidate.vendor.lower() == vendor.lower()
        ):
            existing = candidate
            break

    if existing:
        new_amount, new_unit = combine_amounts_and_units(
            existing.amount,
            existing.amount_unit,
            amount,
            amount_unit,
        )
        existing.amount = new_amount
        existing.amount_unit = new_unit
        existing_purpose = clean_purpose(existing.purpose)
        if purpose and purpose not in existing_purpose:
            existing.purpose = f"{existing_purpose}, {purpose}".strip(", ")
        else:
            existing.purpose = existing_purpose
        if priority_flag:
            existing.priority = True
        # Item was manually added or combined -> confirm it so it is not in "not confirmed" status
        existing.locked = True
        _set_item_audit(existing, request)
        existing.save(
            update_fields=[
                "amount",
                "amount_unit",
                "purpose",
                "locked",
                "priority",
                "status_changed_at",
                "status_changed_by",
                "status_changed_by_name",
                "updated_at",
            ]
        )
    else:
        max_order = shopping_list.items.count()
        audit_user = request.user if request.user.is_authenticated else None
        audit_user_name = request.user.username if request.user.is_authenticated else "unknown"
        ShoppingListItem.objects.create(
            shopping_list=shopping_list,
            name=raw_name,
            amount=amount,
            amount_unit=amount_unit,
            brand=brand,
            vendor=vendor,
            purpose=purpose,
            category=category,
            aisle=aisle,
            priority=priority_flag,
            status=ItemStatus.NEED,
            locked=True,
            order=max_order + 1,
            status_changed_at=timezone.now(),
            status_changed_by=audit_user,
            status_changed_by_name=audit_user_name,
        )

    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, shopping_list, group_by)
    if existing:
        unit_str = f" {existing.unit_display}" if existing.unit_display else ""
        toast = f"You updated '{existing.name}' to {existing.amount_display}{unit_str}"
        broadcast_toast = f"{existing.changed_by_display} updated '{existing.name}' to {existing.amount_display}{unit_str}"
    else:
        toast = f"You added '{raw_name}' to the shopping list"
        broadcast_toast = f"{audit_user_name} added '{raw_name}' to the shopping list"

    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=broadcast_toast,
        actor_name=existing.changed_by_display if existing else audit_user_name,
        sender_client_id=_get_client_id(request),
    )
    return render_list_response(request, context, toast_message=toast)


def edit_item(request: HttpRequest, item_id: int) -> HttpResponse:
    """
    Render the edit modal dialog (GET) or update item details (POST).

    Also teaches store aisle learning cache if aisle is edited while a store is active.

    Args:
        request: The HTTP request.
        item_id: Primary key of the item.

    Returns:
        Rendered modal HTML on GET, or updated list partial on POST.
    """
    item = get_object_or_404(ShoppingListItem, id=item_id)
    forbidden = _check_write_permission(request, item.shopping_list)
    if forbidden:
        return forbidden

    if request.method == "POST":
        old_amount = item.amount
        old_unit = item.amount_unit

        item.name = request.POST.get("name", item.name).strip()
        amount_string = request.POST.get("amount", str(item.amount))
        parsed_amount, parsed_unit = parse_amount_and_unit(amount_string)
        item.amount = parsed_amount
        raw_unit = request.POST.get("amount_unit", "").strip()
        if raw_unit:
            item.amount_unit = raw_unit
        elif parsed_unit:
            item.amount_unit = parsed_unit
        item.brand = request.POST.get("brand", item.brand).strip()
        item.vendor = request.POST.get("vendor", item.vendor).strip()
        item.category = request.POST.get("category", item.category).strip()
        item.aisle = request.POST.get("aisle", item.aisle).strip()
        item.purpose = clean_purpose(request.POST.get("purpose", item.purpose).strip()) or "one-time purchase"
        item.priority = request.POST.get("priority") in ("true", "1", "on", True)

        # Check if editing this item allows it to combine with another item on the list
        normalized_name = singularize(item.name.lower())
        existing: ShoppingListItem | None = None
        for candidate in item.shopping_list.items.filter(status=item.status).exclude(id=item.id):
            if (
                singularize(candidate.name.lower()) == normalized_name
                and can_combine_units(candidate.amount_unit, item.amount_unit)
                and candidate.brand.lower() == item.brand.lower()
                and candidate.vendor.lower() == item.vendor.lower()
            ):
                existing = candidate
                break

        if existing:
            if item.priority:
                existing.priority = True
            # Combine into existing item
            combined_amount, combined_unit = combine_amounts_and_units(
                existing.amount,
                existing.amount_unit,
                item.amount,
                item.amount_unit,
            )
            existing.amount = combined_amount
            existing.amount_unit = combined_unit
            existing_purpose = clean_purpose(existing.purpose)
            item_purpose = clean_purpose(item.purpose)
            if item_purpose and item_purpose not in existing_purpose:
                existing.purpose = f"{existing_purpose}, {item_purpose}".strip(", ")
            else:
                existing.purpose = existing_purpose
            if item.source_meal and not existing.source_meal:
                existing.source_meal = item.source_meal
            if item.source_recipe and not existing.source_recipe:
                existing.source_recipe = item.source_recipe

            # Requirement: If an item is combined, it gets the "not confirmed" status
            existing.locked = False
            _set_item_audit(existing, request)
            existing.save()

            # Delete the redundant edited item
            item.delete()

            # Update store aisle learning cache if aisle is set
            if existing.aisle and existing.shopping_list.active_store:
                StoreItemAisle.objects.update_or_create(
                    store=existing.shopping_list.active_store,
                    item_name_normalized=normalized_name,
                    defaults={
                        "aisle_name": existing.aisle,
                        "source": "manual",
                    },
                )

            group_by = request.GET.get("group_by", GroupBy.CATEGORY)
            context = _build_list_context(request, existing.shopping_list, group_by)
            unit_str = f" {existing.unit_display}" if existing.unit_display else ""
            toast = f"Combined into '{existing.name}' ({existing.amount_display}{unit_str})"
            broadcast_shopping_list_update(
                shopping_list=existing.shopping_list,
                toast_message=f"✏️ {existing.changed_by_display} combined '{existing.name}' into {existing.amount_display}{unit_str}",
                actor_name=existing.changed_by_display,
                sender_client_id=_get_client_id(request),
            )
            return render_list_response(request, context, toast_message=toast)

        # Requirement: If not combined, check if amount or unit was increased by editing
        if is_quantity_increased(old_amount, old_unit, item.amount, item.amount_unit):
            item.locked = False

        _set_item_audit(item, request)
        item.save()

        # If user explicitly edited aisle and store is active, update store learning cache
        if item.aisle and item.shopping_list.active_store:
            StoreItemAisle.objects.update_or_create(
                store=item.shopping_list.active_store,
                item_name_normalized=normalized_name,
                defaults={
                    "aisle_name": item.aisle,
                    "source": "manual",
                },
            )

        group_by = request.GET.get("group_by", GroupBy.CATEGORY)
        context = _build_list_context(request, item.shopping_list, group_by)
        broadcast_shopping_list_update(
            shopping_list=item.shopping_list,
            toast_message=f"✏️ {item.changed_by_display} edited '{item.name}'",
            actor_name=item.changed_by_display,
            sender_client_id=_get_client_id(request),
        )
        return render_list_response(request, context, toast_message=f"✏️ You updated '{item.name}'")

    known_categories = get_known_categories()
    known_aisles = get_known_aisles(item.shopping_list.active_store)
    return render(
        request,
        "shopping/partials/item_edit_modal.html",
        {
            "item": item,
            "known_categories": known_categories,
            "known_aisles": known_aisles,
        },
    )


@require_POST
def delete_item(request: HttpRequest, item_id: int) -> HttpResponse:
    """
    Delete a shopping list item permanently.

    Args:
        request: The POST request.
        item_id: Primary key of the item to delete.

    Returns:
        Rendered HTML partial with updated list and toast notification.
    """
    item = get_object_or_404(ShoppingListItem, id=item_id)
    forbidden = _check_write_permission(request, item.shopping_list)
    if forbidden:
        return forbidden

    item_name = item.name
    shopping_list = item.shopping_list
    item.delete()

    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, shopping_list, group_by)
    actor_name = request.user.username if request.user.is_authenticated else "unknown"
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"🗑 '{item_name}' was removed from the list",
        actor_name=actor_name,
        sender_client_id=_get_client_id(request),
    )
    return render_list_response(request, context, toast_message=f"🗑 You deleted '{item_name}'")


@require_POST
def toggle_lock_item(request: HttpRequest, item_id: int) -> HttpResponse:
    """
    Toggle the 'Need' confirmation lock during Pantry Check mode.

    Args:
        request: The POST request.
        item_id: Primary key of the item.

    Returns:
        Rendered HTML partial with updated list and toast notification.
    """
    item = get_object_or_404(ShoppingListItem, id=item_id)
    forbidden = _check_write_permission(request, item.shopping_list)
    if forbidden:
        return forbidden

    item.locked = not item.locked
    _set_item_audit(item, request)
    item.save(
        update_fields=[
            "locked",
            "status_changed_at",
            "status_changed_by",
            "status_changed_by_name",
            "updated_at",
        ]
    )

    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, item.shopping_list, group_by)
    if item.locked:
        toast = f'📋 You set \'{item.name}\' to "needed"'
        broadcast_toast = f'📋 {item.changed_by_display} set \'{item.name}\' to "needed"'
    else:
        toast = f"You unchecked '{item.name}'"
        broadcast_toast = f"{item.changed_by_display} unchecked '{item.name}'"

    broadcast_shopping_list_update(
        shopping_list=item.shopping_list,
        toast_message=broadcast_toast,
        actor_name=item.changed_by_display,
        sender_client_id=_get_client_id(request),
    )
    return render_list_response(request, context, toast_message=toast)


@require_POST
def toggle_priority(request: HttpRequest, item_id: int) -> HttpResponse:
    """
    Toggle priority status for a shopping list item.
    """
    item = get_object_or_404(ShoppingListItem, id=item_id)
    forbidden = _check_write_permission(request, item.shopping_list)
    if forbidden:
        return forbidden

    item.priority = not item.priority
    _set_item_audit(item, request)
    item.save(
        update_fields=[
            "priority",
            "status_changed_at",
            "status_changed_by",
            "status_changed_by_name",
            "updated_at",
        ]
    )

    group_by = request.GET.get("group_by", GroupBy.CATEGORY)
    context = _build_list_context(request, item.shopping_list, group_by)

    status_str = "marked as High Priority" if item.priority else "removed from Priority"
    toast = f"📌 '{item.name}' {status_str}"

    broadcast_shopping_list_update(
        shopping_list=item.shopping_list,
        toast_message=f"📌 {item.changed_by_display} {status_str} '{item.name}'",
        actor_name=item.changed_by_display,
        sender_client_id=_get_client_id(request),
    )

    return render_list_response(request, context, toast_message=toast)


@require_POST
def set_store(request: HttpRequest) -> HttpResponse:
    """
    Update the active store location on the primary shopping list.

    Args:
        request: The POST request containing store_id.

    Returns:
        Rendered HTML partial of the shopping list.
    """
    shopping_list = get_active_list(request)
    forbidden = _check_write_permission(request, shopping_list)
    if forbidden:
        return forbidden

    store_id = request.POST.get("store_id")
    if store_id:
        store = get_object_or_404(StoreLocation, id=store_id)
        shopping_list.active_store = store
        shopping_list.save(update_fields=["active_store"])
    else:
        shopping_list.active_store = None
        shopping_list.save(update_fields=["active_store"])

    group_by = request.GET.get(
        "group_by",
        GroupBy.AISLE if shopping_list.active_store else GroupBy.CATEGORY,
    )
    context = _build_list_context(request, shopping_list, group_by)
    actor_name = request.user.username if request.user.is_authenticated else "unknown"
    store_name = shopping_list.active_store.name if shopping_list.active_store else "None"
    toast = f"📍 Active store set to '{store_name}'" if shopping_list.active_store else "Cleared active store"
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=toast,
        actor_name=actor_name,
        sender_client_id=_get_client_id(request),
    )
    return render_list_response(request, context, toast_message=toast)


@require_POST
def find_nearest_store(request: HttpRequest) -> HttpResponse:
    """
    Find the 5 closest physical supermarkets based on GPS coordinates
    and render the selection modal dialog.

    Args:
        request: The POST request containing latitude and longitude.

    Returns:
        Rendered HTML partial of the nearest stores modal dialog.
    """
    try:
        latitude = float(request.POST.get("latitude", 0))
        longitude = float(request.POST.get("longitude", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid coordinates"}, status=400)

    nearest_matches = get_nearest_stores(latitude, longitude, limit=5)
    shopping_list = get_active_list(request)
    group_by = request.GET.get("group_by", GroupBy.AISLE)
    mode = request.GET.get("mode", "shopping")

    return render(
        request,
        "shopping/partials/nearest_stores_modal.html",
        {
            "nearest_matches": nearest_matches,
            "active_store": shopping_list.active_store,
            "shopping_list": shopping_list,
            "group_by": group_by,
            "mode": mode,
            "latitude": latitude,
            "longitude": longitude,
        },
    )


@require_POST
def reorder_items(request: HttpRequest) -> HttpResponse:
    """
    Persist new drag-and-drop sort order indices for individual items within a section.

    Args:
        request: POST request with item_ids[] list.

    Returns:
        204 No Content response on success, or 400 JsonResponse on error.
    """
    shopping_list = get_active_list(request)
    forbidden = _check_write_permission(request, shopping_list)
    if forbidden:
        return forbidden

    try:
        item_ids = request.POST.getlist("item_ids[]")
        if not item_ids:
            body = json.loads(request.body.decode()) if request.body else {}
            item_ids = body.get("item_ids", [])

        for index, item_id in enumerate(item_ids):
            ShoppingListItem.objects.filter(id=int(item_id)).update(order=index)

        shopping_list = get_active_list(request)
        broadcast_shopping_list_update(
            shopping_list=shopping_list,
            sender_client_id=_get_client_id(request),
        )
        return HttpResponse(status=204)
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=400)


@require_POST
def reorder_sections(request: HttpRequest) -> HttpResponse:
    """
    Persist custom sequence order for entire category or aisle section blocks.

    Args:
        request: POST request with group_by and group_names[] list.

    Returns:
        204 No Content response on success, or 400 JsonResponse on error.
    """
    shopping_list = get_active_list(request)
    forbidden = _check_write_permission(request, shopping_list)
    if forbidden:
        return forbidden

    try:
        group_by = request.POST.get("group_by", GroupBy.CATEGORY)
        group_names = request.POST.getlist("group_names[]")
        if not group_names:
            body = json.loads(request.body.decode()) if request.body else {}
            group_names = body.get("group_names", [])
            group_by = body.get("group_by", group_by)

        if group_names:
            orders = dict(shopping_list.custom_section_order or {})
            orders[group_by] = group_names
            shopping_list.custom_section_order = orders
            shopping_list.save(update_fields=["custom_section_order", "updated_at"])

            # Sync item order numbers so walking sequence strictly respects new section sequence
            current_order_index = 0
            for group_name in group_names:
                if str(group_by) == GroupBy.AISLE:
                    group_items = shopping_list.items.filter(
                        status=ItemStatus.NEED, aisle=group_name
                    ).order_by("order", "id")
                else:
                    group_items = shopping_list.items.filter(
                        status=ItemStatus.NEED, category__iexact=group_name
                    ).order_by("order", "id")
                for item in group_items:
                    item.order = current_order_index
                    item.save(update_fields=["order"])
                    current_order_index += 1

            broadcast_shopping_list_update(
                shopping_list=shopping_list,
                sender_client_id=_get_client_id(request),
            )

        return HttpResponse(status=204)
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=400)
