"""
Preset List management and scheduling service.

Handles:
- Preset template lifecycle (create, edit, delete, items).
- Manual loading of preset lists onto the primary shopping list.
- Automated scheduled recurrence:
  On the user-configured interval (default 1 week) from last occurrence (or overridden next occurrence),
  all entries previously added to the shopping list from the given preset list are removed
  regardless of status, and all active preset items are immediately re-added.
"""

import logging
from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from apps.core.categorizer import categorizer
from apps.core.models import Workspace
from apps.core.utils import parse_amount_and_unit
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.store_service import resolve_store_aisle, warm_store_aisles_async

logger = logging.getLogger(__name__)


def get_workspace_presets(workspace: Workspace) -> list[ShoppingList]:
    """
    Retrieve all preset list templates belonging to the given workspace.

    Args:
        workspace: Workspace instance.

    Returns:
        List of ShoppingList instances with is_preset=True.
    """
    return list(
        workspace.shopping_lists.filter(is_preset=True)
        .prefetch_related("items")
        .order_by("name")
    )


def create_preset_list(
    workspace: Workspace,
    name: str,
    interval_days: int = 7,
    is_schedule_enabled: bool = False,
    next_occurrence: timezone.datetime | None = None,
) -> ShoppingList:
    """
    Create a new preset list template within the workspace.

    Args:
        workspace: Target Workspace.
        name: Name of the preset list (e.g. 'Spices', 'Weekly Essentials').
        interval_days: Recurrence interval in days (default: 7).
        is_schedule_enabled: Whether automatic refresh scheduling is active.
        next_occurrence: Scheduled datetime for the first or next occurrence.

    Returns:
        The newly created ShoppingList preset instance.
    """
    clean_name = name.strip() or "Untitled Preset"
    days = interval_days if interval_days and interval_days > 0 else 7

    if is_schedule_enabled and next_occurrence is None:
        next_occurrence = timezone.now() + timezone.timedelta(days=days)

    preset_list = ShoppingList.objects.create(
        workspace=workspace,
        owner=workspace.owner,
        name=clean_name,
        is_preset=True,
        interval_days=days,
        is_schedule_enabled=is_schedule_enabled,
        next_occurrence=next_occurrence,
    )
    logger.info("Created preset list '%s' in workspace '%s'", clean_name, workspace.name)
    return preset_list


def add_preset_item(
    preset_list: ShoppingList,
    name: str,
    amount: str | Decimal = Decimal("1.00"),
    amount_unit: str = "",
    brand: str = "",
    vendor: str = "",
    category: str = "",
    optional: bool = False,
    is_active: bool = True,
) -> ShoppingListItem:
    """
    Add a new item to a preset list template.

    Args:
        preset_list: ShoppingList preset instance.
        name: Item title.
        amount: Quantity string or Decimal.
        amount_unit: Unit label (e.g. 'can', 'oz', 'lb').
        brand: Optional brand name.
        vendor: Optional vendor or store preference.
        category: Department/category name (auto-detected if empty).
        optional: Whether this item is optional.
        is_active: Whether this item is active on automated schedule runs.

    Returns:
        The created ShoppingListItem instance.
    """
    clean_name = name.strip()
    if isinstance(amount, str):
        parsed_amount, parsed_unit = parse_amount_and_unit(amount)
        amount_val = parsed_amount or Decimal("1.00")
        unit_val = (amount_unit.strip() or parsed_unit).strip()
    else:
        amount_val = amount
        unit_val = amount_unit.strip()

    cat = category.strip() or categorizer.get_category(clean_name)

    item = ShoppingListItem.objects.create(
        shopping_list=preset_list,
        name=clean_name,
        amount=amount_val,
        amount_unit=unit_val,
        brand=brand.strip(),
        vendor=vendor.strip(),
        category=cat,
        optional=optional,
        is_active=is_active,
        purpose=f"Preset: {preset_list.name}",
        status=ItemStatus.NEED,
    )
    logger.debug("Added item '%s' to preset '%s'", clean_name, preset_list.name)
    return item


def delete_preset_item(preset_list: ShoppingList, item_id: int) -> bool:
    """
    Delete an item from a preset list template.

    Args:
        preset_list: Target preset list.
        item_id: ID of the ShoppingListItem to delete.

    Returns:
        True if item was deleted, False otherwise.
    """
    deleted, _ = preset_list.items.filter(id=item_id).delete()
    return deleted > 0


def update_preset_schedule(
    preset_list: ShoppingList,
    is_schedule_enabled: bool,
    interval_days: int = 7,
    next_occurrence: timezone.datetime | None = None,
    request: HttpRequest | None = None,
) -> ShoppingList:
    """
    Update schedule settings for a preset list.

    Args:
        preset_list: ShoppingList preset instance.
        is_schedule_enabled: Toggle for automated recurring refresh.
        interval_days: Recurrence interval in days from last occurrence.
        next_occurrence: Scheduled next occurrence datetime (user can override).
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        Updated preset list instance.
    """
    days = interval_days if interval_days and interval_days > 0 else 7
    preset_list.is_schedule_enabled = is_schedule_enabled
    preset_list.interval_days = days

    if is_schedule_enabled:
        if next_occurrence is not None:
            preset_list.next_occurrence = next_occurrence
        elif not preset_list.next_occurrence:
            preset_list.next_occurrence = timezone.now() + timezone.timedelta(days=days)
    else:
        # If disabled, keep or clear next_occurrence
        preset_list.next_occurrence = next_occurrence

    preset_list.save(update_fields=["is_schedule_enabled", "interval_days", "next_occurrence", "updated_at"])
    logger.info("Updated schedule for preset '%s': enabled=%s, interval=%d days, next=%s",
                preset_list.name, is_schedule_enabled, days, preset_list.next_occurrence)

    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    target_list = preset_list.workspace.get_primary_list() if preset_list.workspace else None
    status_str = "enabled" if is_schedule_enabled else "disabled"
    broadcast_shopping_list_update(
        shopping_list=target_list,
        toast_message=f"📅 Schedule {status_str} for preset '{preset_list.name}'",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )

    return preset_list


def load_preset_items_to_shopping_list(
    preset_list: ShoppingList,
    target_list: ShoppingList,
    item_ids: list[int] | None = None,
    replace_existing: bool = False,
    request: HttpRequest | None = None,
) -> list[ShoppingListItem]:
    """
    Load items from a preset list onto the primary shopping list.

    Args:
        preset_list: Source preset list template.
        target_list: Target primary shopping list.
        item_ids: Optional list of item IDs to selectively load (None loads all).
        replace_existing: If True, removes all previous entries from this preset list first.
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        List of newly created ShoppingListItem records on the target list.
    """
    if replace_existing:
        target_list.items.filter(source_preset=preset_list).delete()

    source_items = preset_list.items.all().order_by("order", "id")
    if item_ids is not None:
        source_items = source_items.filter(id__in=item_ids)

    created_items: list[ShoppingListItem] = []
    store = target_list.active_store

    for item in source_items:
        aisle = item.aisle
        if not aisle and store:
            aisle_info = resolve_store_aisle(store, item.name, db_only=True)
            aisle = aisle_info.get("aisle_name", "") if aisle_info else ""

        cat = item.category or categorizer.get_category(item.name)

        new_item = ShoppingListItem.objects.create(
            shopping_list=target_list,
            name=item.name,
            amount=item.amount,
            amount_unit=item.amount_unit,
            brand=item.brand,
            vendor=item.vendor,
            category=cat,
            aisle=aisle,
            purpose=f"Preset: {preset_list.name}",
            optional=item.optional,
            status=ItemStatus.NEED,
            locked=True,
            source_preset=preset_list,
        )
        created_items.append(new_item)

    # Warm missing aisles in background so user request returns immediately
    if store:
        warm_store_aisles_async(target_list)

    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    broadcast_shopping_list_update(
        shopping_list=target_list,
        toast_message=f"Loaded {len(created_items)} items from preset '{preset_list.name}'",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )
    return created_items


def unload_preset_from_shopping_list(
    preset_list: ShoppingList,
    target_list: ShoppingList,
    request: HttpRequest | None = None,
) -> int:
    """
    Remove all items previously loaded from a preset list from the primary shopping list.

    Args:
        preset_list: Source preset list template.
        target_list: Target primary shopping list.
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        Number of items removed.
    """
    removed_count, _ = target_list.items.filter(source_preset=preset_list).delete()
    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    broadcast_shopping_list_update(
        shopping_list=target_list,
        toast_message=f"Removed '{preset_list.name}' items from shopping list",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )
    return removed_count


def apply_preset_scheduled_refresh(
    preset_list: ShoppingList,
    target_list: ShoppingList | None = None,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """
    Execute a scheduled refresh for a preset list.

    Behavior:
    1. Removes all entries previously added to the primary shopping list from this preset list,
       regardless of their status (NEED, GOT, HAVE, DONT_NEED).
    2. Immediately re-adds all active items from the preset list onto the shopping list.
    3. Updates last_applied_at to now, and computes the next_occurrence based on interval_days.
    4. Broadcasts real-time WebSocket updates.

    Args:
        preset_list: The preset ShoppingList template.
        target_list: Optional target ShoppingList (defaults to workspace primary list).
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        Dict containing removed_count, added_count, and updated preset_list.
    """
    if target_list is None:
        if not preset_list.workspace:
            raise ValueError(f"Preset list '{preset_list.name}' has no assigned workspace.")
        target_list = preset_list.workspace.get_primary_list()
        if not target_list:
            target_list = ShoppingList.objects.create(
                name=f"{preset_list.workspace.name} Shopping List",
                workspace=preset_list.workspace,
                owner=preset_list.workspace.owner,
                is_preset=False,
            )

    # 1. Remove ALL previous entries from this preset list regardless of status
    old_items = target_list.items.filter(source_preset=preset_list)
    removed_count = old_items.count()
    old_items.delete()
    logger.info("Scheduled refresh for '%s': removed %d previous items from shopping list",
                preset_list.name, removed_count)

    # 2. Right away, re-add all active items from the preset list (excludes paused/inactive items)
    active_items = preset_list.items.filter(is_active=True).order_by("order", "id")
    added_items: list[ShoppingListItem] = []
    store = target_list.active_store

    for item in active_items:
        aisle = item.aisle
        if not aisle and store:
            aisle_info = resolve_store_aisle(store, item.name, db_only=True)
            aisle = aisle_info.get("aisle_name", "") if aisle_info else ""

        cat = item.category or categorizer.get_category(item.name)

        new_item = ShoppingListItem.objects.create(
            shopping_list=target_list,
            name=item.name,
            amount=item.amount,
            amount_unit=item.amount_unit,
            brand=item.brand,
            vendor=item.vendor,
            category=cat,
            aisle=aisle,
            purpose=f"Preset: {preset_list.name}",
            optional=item.optional,
            status=ItemStatus.NEED,
            locked=True,
            source_preset=preset_list,
        )
        added_items.append(new_item)

    # Warm missing aisles in background so user request returns immediately
    if store:
        warm_store_aisles_async(target_list)

    # 3. Advance schedule timestamps
    now = timezone.now()
    days = preset_list.interval_days if preset_list.interval_days and preset_list.interval_days > 0 else 7
    preset_list.last_applied_at = now
    preset_list.next_occurrence = now + timezone.timedelta(days=days)
    preset_list.save(update_fields=["last_applied_at", "next_occurrence", "updated_at"])

    # 4. Broadcast update to connected clients
    actor_name = request.user.username if (request and request.user.is_authenticated) else "system"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    broadcast_shopping_list_update(
        shopping_list=target_list,
        toast_message=f"Preset refresh: '{preset_list.name}' ({len(added_items)} items added)",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )

    logger.info("Scheduled refresh for '%s' complete: re-added %d items. Next run at %s",
                preset_list.name, len(added_items), preset_list.next_occurrence)

    return {
        "preset_list": preset_list,
        "removed_count": removed_count,
        "added_count": len(added_items),
        "next_occurrence": preset_list.next_occurrence,
    }


def check_and_apply_due_preset_schedules(
    workspace: Workspace,
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """
    Check all preset lists in the workspace and execute any that are due for scheduled refresh.

    Args:
        workspace: Workspace to inspect.
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        List of execution result dicts for any presets that ran.
    """
    now = timezone.now()
    due_presets = workspace.shopping_lists.filter(
        is_preset=True,
        is_schedule_enabled=True,
        next_occurrence__isnull=False,
        next_occurrence__lte=now,
    )

    results: list[dict[str, Any]] = []
    target_list = workspace.get_primary_list()

    for preset in due_presets:
        try:
            res = apply_preset_scheduled_refresh(preset, target_list=target_list, request=request)
            results.append(res)
        except Exception as e:
            logger.exception("Error applying scheduled refresh for preset '%s': %s", preset.name, e)

    return results
