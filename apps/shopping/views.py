import json
from collections import defaultdict
from decimal import Decimal

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.categorizer import categorizer
from apps.core.utils import parse_amount_and_unit, singularize
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, StoreLocation
from apps.shopping.services.store_service import (
    DEPARTMENT_ORDER,
    get_aisle_sort_key,
    get_known_aisles,
    get_known_categories,
    get_nearest_stores,
    resolve_store_aisle,
)


def get_active_list(request) -> ShoppingList:
    """Helper to retrieve or initialize the primary shopping list."""
    shopping_list = ShoppingList.objects.filter(is_preset=False).first()
    if not shopping_list:
        default_store = StoreLocation.objects.first()
        shopping_list = ShoppingList.objects.create(
            name="Main Shopping List",
            is_preset=False,
            active_store=default_store,
        )
    return shopping_list


def _build_list_context(request, shopping_list: ShoppingList, group_by: str = "category", mode: str | None = None):
    items = shopping_list.items.all().order_by("order", "id")

    if not mode and request:
        mode = request.GET.get("mode") or request.POST.get("mode") or request.session.get("shopping_mode", "shopping")
    if mode not in ("shopping", "pantry"):
        mode = "shopping"
    if request:
        request.session["shopping_mode"] = mode

    need_items = [i for i in items if i.status == ItemStatus.NEED]
    got_items = [i for i in items if i.status == ItemStatus.GOT]
    pantry_items = [i for i in items if i.status in (ItemStatus.HAVE, ItemStatus.DONT_NEED)]

    custom_orders = shopping_list.custom_section_order or {}
    custom_order_list = custom_orders.get(group_by, [])
    custom_order_map = {name.lower(): idx for idx, name in enumerate(custom_order_list)}

    # Group need_items
    grouped_need = defaultdict(list)
    if group_by == "aisle" and shopping_list.active_store:
        for item in need_items:
            aisle = item.get_effective_aisle()
            grouped_need[aisle].append(item)

        def aisle_sort_key_fn(k):
            if k.lower() in custom_order_map:
                return (0, custom_order_map[k.lower()])
            return (1, get_aisle_sort_key(k))

        sorted_keys = sorted(grouped_need.keys(), key=aisle_sort_key_fn)
        sorted_grouped_need = {k: grouped_need[k] for k in sorted_keys}
    else:
        for item in need_items:
            cat = (item.category or "other").title()
            grouped_need[cat].append(item)

        def cat_sort_key_fn(k):
            if k.lower() in custom_order_map:
                return (0, custom_order_map[k.lower()])
            return (1, DEPARTMENT_ORDER.get(k.lower(), 200))

        sorted_keys = sorted(grouped_need.keys(), key=cat_sort_key_fn)
        sorted_grouped_need = {k: grouped_need[k] for k in sorted_keys}

    stores = StoreLocation.objects.all().order_by("name")
    known_categories = get_known_categories()
    known_aisles = get_known_aisles(shopping_list.active_store)

    return {
        "shopping_list": shopping_list,
        "grouped_need": sorted_grouped_need,
        "need_count": len(need_items),
        "got_items": got_items,
        "got_count": len(got_items),
        "pantry_items": pantry_items,
        "pantry_count": len(pantry_items),
        "group_by": group_by,
        "stores": stores,
        "active_store": shopping_list.active_store,
        "known_categories": known_categories,
        "known_aisles": known_aisles,
        "mode": mode,
    }


def shopping_list_view(request):
    shopping_list = get_active_list(request)
    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)

    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "shopping-list-content":
        return render(request, "shopping/partials/list_content.html", context)

    return render(request, "shopping/list.html", context)


def _set_item_audit(item: ShoppingListItem, request) -> None:
    item.status_changed_at = timezone.now()
    if request.user.is_authenticated:
        item.status_changed_by = request.user
        item.status_changed_by_name = request.user.username
    else:
        item.status_changed_by = None
        item.status_changed_by_name = "You"


@require_POST
def set_item_status(request, item_id: int, new_status: str):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    if new_status in ItemStatus.values:
        item.status = new_status
        _set_item_audit(item, request)
        item.save(update_fields=["status", "status_changed_at", "status_changed_by", "status_changed_by_name", "updated_at"])

    shopping_list = item.shopping_list
    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)

    status_messages = {
        ItemStatus.GOT: f"🛒 You moved '{item.name}' to Cart",
        ItemStatus.HAVE: f"🏠 You marked '{item.name}' as Already in Pantry",
        ItemStatus.DONT_NEED: f"⏭ You skipped '{item.name}'",
        ItemStatus.NEED: f"📋 You moved '{item.name}' back to To Buy",
    }
    context["toast_message"] = status_messages.get(new_status, f"You updated '{item.name}'")
    return render(request, "shopping/partials/list_content.html", context)


@require_POST
def add_item(request):
    shopping_list = get_active_list(request)
    raw_name = request.POST.get("name", "").strip()
    if not raw_name:
        return redirect("shopping:list")

    raw_amount = request.POST.get("amount", "1")
    amount, amount_unit = parse_amount_and_unit(raw_amount)
    brand = request.POST.get("brand", "").strip()
    vendor = request.POST.get("vendor", "").strip()
    purpose = request.POST.get("purpose", "").strip() or "one-time purchase"

    # Category: use provided or fallback to prediction
    raw_cat = request.POST.get("category", "").strip()
    category = raw_cat or categorizer.get_category(raw_name)

    # Aisle: use provided or fallback to prediction if store selected
    raw_aisle = request.POST.get("aisle", "").strip()
    if raw_aisle:
        aisle = raw_aisle
    elif shopping_list.active_store:
        aisle_info = resolve_store_aisle(shopping_list.active_store, raw_name)
        aisle = aisle_info.get("aisle_name", "")
    else:
        aisle = ""

    # Check for deduplication / stacking with existing NEED item
    norm_name = singularize(raw_name.lower())
    norm_unit = singularize(amount_unit.lower())

    existing = None
    for candidate in shopping_list.items.filter(status=ItemStatus.NEED):
        if (
            singularize(candidate.name.lower()) == norm_name
            and singularize(candidate.amount_unit.lower()) == norm_unit
            and candidate.brand.lower() == brand.lower()
            and candidate.vendor.lower() == vendor.lower()
        ):
            existing = candidate
            break

    if existing:
        existing.amount += amount
        if purpose and purpose not in existing.purpose:
            existing.purpose = f"{existing.purpose}, {purpose}".strip(", ")
        _set_item_audit(existing, request)
        existing.save(update_fields=["amount", "purpose", "status_changed_at", "status_changed_by", "status_changed_by_name", "updated_at"])
    else:
        # Append to end of order
        max_order = shopping_list.items.count()
        user = request.user if request.user.is_authenticated else None
        user_name = request.user.username if request.user.is_authenticated else "You"
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
            status=ItemStatus.NEED,
            order=max_order + 1,
            status_changed_at=timezone.now(),
            status_changed_by=user,
            status_changed_by_name=user_name,
        )

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
    if existing:
        context["toast_message"] = f"You increased the quantity of '{existing.name}' (+{amount})"
    else:
        context["toast_message"] = f"You added '{raw_name}' to the shopping list"
    return render(request, "shopping/partials/list_content.html", context)


def edit_item(request, item_id: int):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    if request.method == "POST":
        item.name = request.POST.get("name", item.name).strip()
        amt_str = request.POST.get("amount", str(item.amount))
        try:
            item.amount = Decimal(amt_str)
        except Exception:
            pass
        item.amount_unit = request.POST.get("amount_unit", item.amount_unit).strip()
        item.brand = request.POST.get("brand", item.brand).strip()
        item.vendor = request.POST.get("vendor", item.vendor).strip()
        item.category = request.POST.get("category", item.category).strip()
        item.aisle = request.POST.get("aisle", item.aisle).strip()
        item.purpose = request.POST.get("purpose", item.purpose).strip() or "one-time purchase"
        _set_item_audit(item, request)
        item.save()

        # If user explicitly edited aisle and store is active, update store learning cache!
        if item.aisle and item.shopping_list.active_store:
            from apps.shopping.models import StoreItemAisle
            StoreItemAisle.objects.update_or_create(
                store=item.shopping_list.active_store,
                item_name_normalized=singularize(item.name.lower()),
                defaults={
                    "aisle_name": item.aisle,
                    "source": "manual",
                },
            )

        group_by = request.GET.get("group_by", "category")
        context = _build_list_context(request, item.shopping_list, group_by)
        context["toast_message"] = f"✏️ You updated '{item.name}'"
        return render(request, "shopping/partials/list_content.html", context)

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
def delete_item(request, item_id: int):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    item_name = item.name
    shopping_list = item.shopping_list
    item.delete()

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
    context["toast_message"] = f"🗑 You deleted '{item_name}'"
    return render(request, "shopping/partials/list_content.html", context)


@require_POST
def toggle_lock_item(request, item_id: int):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    item.locked = not item.locked
    _set_item_audit(item, request)
    item.save(update_fields=["locked", "status_changed_at", "status_changed_by", "status_changed_by_name", "updated_at"])

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, item.shopping_list, group_by)
    if item.locked:
        context["toast_message"] = f'📋 You set \'{item.name}\' to "needed"'
    else:
        context["toast_message"] = f"You unchecked '{item.name}'"
    return render(request, "shopping/partials/list_content.html", context)


@require_POST
def set_store(request):
    shopping_list = get_active_list(request)
    store_id = request.POST.get("store_id")
    if store_id:
        store = get_object_or_404(StoreLocation, id=store_id)
        shopping_list.active_store = store
        shopping_list.save(update_fields=["active_store"])
    else:
        shopping_list.active_store = None
        shopping_list.save(update_fields=["active_store"])

    group_by = request.GET.get("group_by", "aisle" if shopping_list.active_store else "category")
    context = _build_list_context(request, shopping_list, group_by)
    return render(request, "shopping/partials/list_content.html", context)


@require_POST
def find_nearest_store(request):
    try:
        lat = float(request.POST.get("latitude", 0))
        lon = float(request.POST.get("longitude", 0))
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid coordinates"}, status=400)

    nearest = get_nearest_stores(lat, lon, limit=1)
    if nearest:
        store = nearest[0]["store"]
        dist = nearest[0]["distance_miles"]
        shopping_list = get_active_list(request)
        shopping_list.active_store = store
        shopping_list.save(update_fields=["active_store"])

        group_by = request.GET.get("group_by", "aisle")
        context = _build_list_context(request, shopping_list, group_by)
        context["toast_message"] = f"Detected nearest store: {store.name} ({dist} mi away)"
        return render(request, "shopping/partials/list_content.html", context)

    return JsonResponse({"error": "No stores found nearby"}, status=404)


@require_POST
def reorder_items(request):
    try:
        item_ids = request.POST.getlist("item_ids[]")
        if not item_ids:
            body = json.loads(request.body.decode())
            item_ids = body.get("item_ids", [])

        for idx, i_id in enumerate(item_ids):
            ShoppingListItem.objects.filter(id=int(i_id)).update(order=idx)

        return HttpResponse(status=204)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@require_POST
def reorder_sections(request):
    try:
        shopping_list = get_active_list(request)
        group_by = request.POST.get("group_by", "category")
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

            # Sync item orders to follow the new section sequence
            current_order = 0
            for g_name in group_names:
                if group_by == "aisle":
                    group_items = shopping_list.items.filter(status=ItemStatus.NEED, aisle=g_name).order_by("order", "id")
                else:
                    group_items = shopping_list.items.filter(status=ItemStatus.NEED, category__iexact=g_name).order_by("order", "id")
                for itm in group_items:
                    itm.order = current_order
                    itm.save(update_fields=["order"])
                    current_order += 1

        return HttpResponse(status=204)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@require_POST
def clear_completed(request):
    shopping_list = get_active_list(request)
    shopping_list.items.filter(status=ItemStatus.GOT).delete()

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
    context["toast_message"] = "You cleared cart items"
    return render(request, "shopping/partials/list_content.html", context)
