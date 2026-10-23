"""
Views and HTMX controllers for Preset Lists.

Provides:
- Preset lists gallery for workspace.
- Preset list CRUD and item management (matching legacy capabilities: name, amount, unit, optional, brand, vendor, category).
- Modal for selectively loading preset items into the primary shopping list.
- Configurable recurrence schedule: user-configured interval (defaulting to 1 week),
  allowing user to change next occurrence.
- Immediate manual schedule trigger ('Run Schedule Now').
"""

import logging
from datetime import datetime
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.categorizer import categorizer
from apps.core.services.workspace_service import get_active_workspace
from apps.core.utils import parse_amount_and_unit
from apps.shopping.models import ShoppingList
from apps.shopping.services.preset_service import (
    add_preset_item,
    apply_preset_scheduled_refresh,
    check_and_apply_due_preset_schedules,
    create_preset_list,
    delete_preset_item,
    get_workspace_presets,
    load_preset_items_to_shopping_list,
    update_preset_schedule,
)
from apps.shopping.services.store_service import get_known_categories

logger = logging.getLogger(__name__)


def _parse_form_datetime(val: str | None) -> timezone.datetime | None:
    """Parse an HTML5 datetime-local string (YYYY-MM-DDTHH:MM) into an aware datetime."""
    if not val or not val.strip():
        return None
    cleaned = val.strip()
    # If standard ISO without seconds
    try:
        dt = parse_datetime(cleaned)
        if dt is None:
            dt = datetime.strptime(cleaned, "%Y-%m-%dT%H:%M")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except Exception as e:
        logger.warning("Could not parse datetime string '%s': %s", val, e)
        return None


def preset_list_index(request: HttpRequest) -> HttpResponse:
    """
    Display all preset lists belonging to the current workspace.

    Automatically checks and applies any due schedules for this workspace before rendering.
    """
    workspace = get_active_workspace(request)
    if not workspace:
        return redirect("shopping:list")

    # Evaluate any due schedules
    check_and_apply_due_preset_schedules(workspace, request=request)

    preset_lists = get_workspace_presets(workspace)
    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (user and user.is_authenticated) else True
    user_role = workspace.get_user_role(user) if (user and user.is_authenticated) else "owner"

    context: dict[str, Any] = {
        "workspace": workspace,
        "preset_lists": preset_lists,
        "can_write": can_write,
        "user_role": user_role,
        "default_interval_days": 7,
    }
    return render(request, "presets/preset_list_index.html", context)


@require_POST
def preset_create(request: HttpRequest) -> HttpResponse:
    """Create a new preset list in the active workspace."""
    workspace = get_active_workspace(request)
    if not workspace:
        return redirect("shopping:list")

    user = getattr(request, "user", None)
    if user and user.is_authenticated and not workspace.can_write(user):
        return HttpResponseForbidden("You do not have write access to this workspace.")

    name = request.POST.get("name", "").strip() or "New Preset List"
    interval_raw = request.POST.get("interval_days", "7")
    try:
        interval_days = max(1, int(interval_raw))
    except ValueError:
        interval_days = 7

    is_schedule_enabled = request.POST.get("is_schedule_enabled") in ("on", "true", "1")
    next_occurrence = _parse_form_datetime(request.POST.get("next_occurrence"))

    preset_list = create_preset_list(
        workspace=workspace,
        name=name,
        interval_days=interval_days,
        is_schedule_enabled=is_schedule_enabled,
        next_occurrence=next_occurrence,
    )
    return redirect("shopping:preset_detail", preset_id=preset_list.id)


def preset_detail(request: HttpRequest, preset_id: int) -> HttpResponse:
    """
    Display and manage a preset list template, its items, and its schedule.
    """
    preset_list = get_object_or_404(
        ShoppingList.objects.prefetch_related("items"),
        id=preset_id,
        is_preset=True,
    )
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (workspace and user and user.is_authenticated) else True

    items = preset_list.items.all().order_by("order", "id")
    known_categories = get_known_categories()

    context: dict[str, Any] = {
        "workspace": workspace,
        "preset_list": preset_list,
        "items": items,
        "known_categories": known_categories,
        "can_write": can_write,
        "toast_message": request.GET.get("toast", ""),
    }

    if request.headers.get("HX-Target") == "preset-items-container":
        return render(request, "presets/partials/preset_items_list.html", context)

    return render(request, "presets/preset_detail.html", context)


@require_POST
def preset_edit_name(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Update a preset list's title."""
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    new_name = request.POST.get("name", "").strip()
    if new_name:
        preset_list.name = new_name
        preset_list.save(update_fields=["name", "updated_at"])

    if request.headers.get("HX-Request"):
        return render(request, "presets/partials/preset_title.html", {"preset_list": preset_list, "can_write": True})
    return redirect("shopping:preset_detail", preset_id=preset_list.id)


@require_POST
def preset_delete(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Delete an entire preset list template."""
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    preset_name = preset_list.name
    preset_list.delete()
    logger.info("Deleted preset list '%s' (id=%d)", preset_name, preset_id)
    return redirect("shopping:preset_list_index")


@require_POST
def preset_add_item(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Add a new item to the preset list."""
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    name = request.POST.get("name", "").strip()
    if not name:
        return redirect("shopping:preset_detail", preset_id=preset_id)

    amount = request.POST.get("amount", "1")
    amount_unit = request.POST.get("amount_unit", "")
    brand = request.POST.get("brand", "")
    vendor = request.POST.get("vendor", "")
    category = request.POST.get("category", "")
    optional = request.POST.get("optional") in ("on", "true", "1")

    add_preset_item(
        preset_list=preset_list,
        name=name,
        amount=amount,
        amount_unit=amount_unit,
        brand=brand,
        vendor=vendor,
        category=category,
        optional=optional,
    )

    if request.headers.get("HX-Request"):
        items = preset_list.items.all().order_by("order", "id")
        return render(
            request,
            "presets/partials/preset_items_list.html",
            {"preset_list": preset_list, "items": items, "can_write": True},
        )
    return redirect("shopping:preset_detail", preset_id=preset_id)


@require_http_methods(["GET", "POST"])
def preset_edit_item(request: HttpRequest, preset_id: int, item_id: int) -> HttpResponse:
    """Edit or view an item inside a preset list."""
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    item = get_object_or_404(preset_list.items, id=item_id)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (workspace and user and user.is_authenticated) else True

    if request.method == "GET":
        known_categories = get_known_categories()
        return render(
            request,
            "presets/partials/item_edit_modal.html",
            {
                "preset_list": preset_list,
                "item": item,
                "known_categories": known_categories,
                "can_write": can_write,
            },
        )

    if not can_write:
        return HttpResponseForbidden("Read-only access.")

    name = request.POST.get("name", "").strip()
    if name:
        item.name = name
    raw_amount = request.POST.get("amount", "1")
    parsed_amount, parsed_unit = parse_amount_and_unit(raw_amount)
    item.amount = parsed_amount or item.amount
    unit_input = request.POST.get("amount_unit", "").strip()
    item.amount_unit = unit_input if unit_input else (parsed_unit or item.amount_unit)
    item.brand = request.POST.get("brand", "").strip()
    item.vendor = request.POST.get("vendor", "").strip()
    item.category = request.POST.get("category", "").strip() or categorizer.get_category(item.name)
    item.optional = request.POST.get("optional") in ("on", "true", "1")
    item.save()

    items = preset_list.items.all().order_by("order", "id")
    return render(
        request,
        "presets/partials/preset_items_list.html",
        {"preset_list": preset_list, "items": items, "can_write": True},
    )


@require_POST
def preset_delete_item(request: HttpRequest, preset_id: int, item_id: int) -> HttpResponse:
    """Delete an item from the preset list."""
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    delete_preset_item(preset_list, item_id)

    if request.headers.get("HX-Request"):
        items = preset_list.items.all().order_by("order", "id")
        return render(
            request,
            "presets/partials/preset_items_list.html",
            {"preset_list": preset_list, "items": items, "can_write": True},
        )
    return redirect("shopping:preset_detail", preset_id=preset_id)


@require_POST
def preset_update_schedule(request: HttpRequest, preset_id: int) -> HttpResponse:
    """
    Update the recurrence schedule settings for a preset list.

    Allows user to configure:
    - is_schedule_enabled: toggle on/off.
    - interval_days: user-configured interval (defaulting to 1 week / 7 days).
    - next_occurrence: user-configurable next run date/time override.
    """
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    is_schedule_enabled = request.POST.get("is_schedule_enabled") in ("on", "true", "1")
    interval_raw = request.POST.get("interval_days", "7")
    try:
        interval_days = max(1, int(interval_raw))
    except ValueError:
        interval_days = 7

    next_occurrence = _parse_form_datetime(request.POST.get("next_occurrence"))

    update_preset_schedule(
        preset_list=preset_list,
        is_schedule_enabled=is_schedule_enabled,
        interval_days=interval_days,
        next_occurrence=next_occurrence,
    )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "presets/partials/schedule_section.html",
            {
                "preset_list": preset_list,
                "can_write": True,
                "toast_message": "Schedule updated successfully",
            },
        )
    return redirect("shopping:preset_detail", preset_id=preset_id)


@require_POST
def preset_run_schedule_now(request: HttpRequest, preset_id: int) -> HttpResponse:
    """
    Immediately execute the scheduled refresh action for a preset list.

    Removes all previous items loaded from this preset list from the primary shopping list
    (regardless of their status: NEED, GOT, HAVE, DONT_NEED), and immediately re-adds all
    active preset items.
    """
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    res = apply_preset_scheduled_refresh(preset_list, request=request)
    msg = (
        f"Schedule executed: Removed {res['removed_count']} previous entries, "
        f"re-added {res['added_count']} active items."
    )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "presets/partials/schedule_section.html",
            {
                "preset_list": preset_list,
                "can_write": True,
                "toast_message": msg,
            },
        )

    return redirect(f"/preset-lists/{preset_id}/?toast={msg}")


def preset_load_modal(request: HttpRequest, preset_id: int) -> HttpResponse:
    """
    Render modal dialog allowing user to choose items to load onto the shopping list.

    Matches legacy behavior: checkboxes for items, pre-selected, option to replace previous items.
    """
    preset_list = get_object_or_404(
        ShoppingList.objects.prefetch_related("items"),
        id=preset_id,
        is_preset=True,
    )
    items = preset_list.items.all().order_by("order", "id")
    return render(
        request,
        "presets/partials/load_modal.html",
        {
            "preset_list": preset_list,
            "items": items,
        },
    )


@require_POST
def preset_load_items(request: HttpRequest, preset_id: int) -> HttpResponse:
    """
    Load selected items from the preset list into the primary shopping list.
    """
    preset_list = get_object_or_404(ShoppingList, id=preset_id, is_preset=True)
    workspace = preset_list.workspace or get_active_workspace(request)
    primary_list = workspace.get_primary_list() if workspace else None
    if not primary_list:
        from apps.shopping.views import get_active_list
        primary_list = get_active_list(request)

    user = getattr(request, "user", None)
    if user and user.is_authenticated and workspace and not workspace.can_write(user):
        return HttpResponseForbidden("Read-only access.")

    selected_ids_raw = request.POST.getlist("item_ids")
    selected_ids = [int(i) for i in selected_ids_raw if i.isdigit()] if selected_ids_raw else None
    replace_existing = request.POST.get("replace_existing") in ("on", "true", "1")

    created = load_preset_items_to_shopping_list(
        preset_list=preset_list,
        target_list=primary_list,
        item_ids=selected_ids,
        replace_existing=replace_existing,
        request=request,
    )

    msg = f"Added {len(created)} items from '{preset_list.name}' to shopping list."

    if request.headers.get("HX-Request"):
        # Close modal and display toast
        return render(
            request,
            "recipes/partials/toast_oob.html",
            {"toast_message": msg},
        )

    return redirect("shopping:list")
