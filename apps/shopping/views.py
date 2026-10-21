import json
from collections import defaultdict
from decimal import Decimal

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.categorizer import categorizer
from apps.core.utils import parse_amount_and_unit, singularize
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, StoreLocation
from apps.shopping.services.store_service import get_nearest_stores, resolve_store_aisle


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


def _build_list_context(request, shopping_list: ShoppingList, group_by: str = "category"):
    items = shopping_list.items.all().order_by("order", "id")

    need_items = [i for i in items if i.status == ItemStatus.NEED]
    got_items = [i for i in items if i.status == ItemStatus.GOT]
    pantry_items = [i for i in items if i.status in (ItemStatus.HAVE, ItemStatus.DONT_NEED)]

    # Group need_items
    grouped_need = defaultdict(list)
    if group_by == "aisle" and shopping_list.active_store:
        for item in need_items:
            aisle = item.get_effective_aisle()
            grouped_need[aisle].append(item)
    else:
        for item in need_items:
            cat = (item.category or "other").title()
            grouped_need[cat].append(item)

    stores = StoreLocation.objects.all().order_by("name")

    return {
        "shopping_list": shopping_list,
        "grouped_need": dict(grouped_need),
        "need_count": len(need_items),
        "got_items": got_items,
        "got_count": len(got_items),
        "pantry_items": pantry_items,
        "pantry_count": len(pantry_items),
        "group_by": group_by,
        "stores": stores,
        "active_store": shopping_list.active_store,
    }


def shopping_list_view(request):
    shopping_list = get_active_list(request)
    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)

    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "shopping-list-content":
        return render(request, "shopping/partials/list_content.html", context)

    return render(request, "shopping/list.html", context)


@require_POST
def set_item_status(request, item_id: int, new_status: str):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    if new_status in ItemStatus.values:
        item.status = new_status
        item.save(update_fields=["status", "updated_at"])

    shopping_list = item.shopping_list
    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
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

    # Category prediction
    category = categorizer.get_category(raw_name)

    # Aisle prediction if store selected
    aisle = ""
    if shopping_list.active_store:
        aisle_info = resolve_store_aisle(shopping_list.active_store, raw_name)
        aisle = aisle_info.get("aisle_name", "")

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
        existing.save(update_fields=["amount", "updated_at"])
    else:
        # Append to end of order
        max_order = shopping_list.items.count()
        ShoppingListItem.objects.create(
            shopping_list=shopping_list,
            name=raw_name,
            amount=amount,
            amount_unit=amount_unit,
            brand=brand,
            vendor=vendor,
            category=category,
            aisle=aisle,
            status=ItemStatus.NEED,
            order=max_order + 1,
        )

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
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
        return render(request, "shopping/partials/list_content.html", context)

    return render(request, "shopping/partials/item_edit_modal.html", {"item": item})


@require_POST
def delete_item(request, item_id: int):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    shopping_list = item.shopping_list
    item.delete()

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
    return render(request, "shopping/partials/list_content.html", context)


@require_POST
def toggle_lock_item(request, item_id: int):
    item = get_object_or_404(ShoppingListItem, id=item_id)
    item.locked = not item.locked
    item.save(update_fields=["locked", "updated_at"])

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, item.shopping_list, group_by)
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
def clear_completed(request):
    shopping_list = get_active_list(request)
    shopping_list.items.filter(status=ItemStatus.GOT, locked=False).delete()

    group_by = request.GET.get("group_by", "category")
    context = _build_list_context(request, shopping_list, group_by)
    return render(request, "shopping/partials/list_content.html", context)
