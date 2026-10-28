"""
Shopping list organization service.

Responsible for partitioning shopping list items by lifecycle status,
grouping active items by aisle or category, and applying custom or store-specific
walking order sorts.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.http import HttpRequest

from apps.shopping.models import GroupBy, ItemStatus, ListMode, ShoppingList, ShoppingListItem
from apps.shopping.services.store_service import DEPARTMENT_ORDER, get_aisle_sort_key


class ShoppingListOrganizer:
    """
    Business logic helper for partitioning, grouping, and ordering shopping list items.

    Encapsulates list display algorithms so that view handlers remain lightweight,
    decoupled, and easily unit-testable.
    """

    @staticmethod
    def partition_items(
        items: Iterable[ShoppingListItem],
    ) -> tuple[list[ShoppingListItem], list[ShoppingListItem], list[ShoppingListItem]]:
        """
        Partition items into active, in-cart, and pantry/skipped categories.

        Args:
            items: An iterable of ShoppingListItem instances.

        Returns:
            A tuple of (need_items, got_items, pantry_items).
        """
        need_items: list[ShoppingListItem] = []
        got_items: list[ShoppingListItem] = []
        pantry_items: list[ShoppingListItem] = []

        for item in items:
            if item.status == ItemStatus.NEED:
                need_items.append(item)
            elif item.status == ItemStatus.GOT:
                got_items.append(item)
            elif item.status in (ItemStatus.HAVE, ItemStatus.DONT_NEED):
                pantry_items.append(item)

        return need_items, got_items, pantry_items

    @staticmethod
    def group_and_sort_need_items(
        need_items: list[ShoppingListItem],
        group_by: GroupBy | str,
        shopping_list: ShoppingList,
    ) -> dict[str, list[ShoppingListItem]]:
        """
        Group active 'NEED' items by category or store aisle, applying custom or heuristic sort orders.

        Args:
            need_items: List of items with status NEED.
            group_by: Grouping strategy ('category' or 'aisle').
            shopping_list: ShoppingList instance possessing active store and custom order metadata.

        Returns:
            Ordered dictionary mapping group header names to lists of items.
        """
        custom_orders: dict[str, list[str]] = shopping_list.custom_section_order or {}
        custom_order_list: list[str] = custom_orders.get(str(group_by), [])
        custom_order_map: dict[str, int] = {
            name.lower(): index for index, name in enumerate(custom_order_list)
        }

        grouped_need: defaultdict[str, list[ShoppingListItem]] = defaultdict(list)

        if str(group_by) == GroupBy.PRIORITY:
            for item in need_items:
                group_name = "Priority Items" if item.priority else "Standard Items"
                grouped_need[group_name].append(item)

            def priority_sort_key_fn(group_name: str) -> tuple[int, Any]:
                group_name_lower = group_name.lower()
                if group_name_lower in custom_order_map:
                    return (0, custom_order_map[group_name_lower])
                return (1, 0 if "priority" in group_name_lower else 1)

            sorted_keys = sorted(grouped_need.keys(), key=priority_sort_key_fn)
            return {group_name: grouped_need[group_name] for group_name in sorted_keys}

        if str(group_by) == GroupBy.AISLE and shopping_list.active_store:
            for item in need_items:
                aisle = item.get_effective_aisle() or "Other"
                grouped_need[aisle].append(item)

            def aisle_sort_key_fn(group_name: str) -> tuple[int, Any]:
                group_name_lower = group_name.lower()
                if group_name_lower in custom_order_map:
                    return (0, custom_order_map[group_name_lower])
                return (1, get_aisle_sort_key(group_name))

            sorted_keys = sorted(grouped_need.keys(), key=aisle_sort_key_fn)
            for key in sorted_keys:
                grouped_need[key].sort(key=lambda it: (not it.priority, it.order, it.id))
            return {group_name: grouped_need[group_name] for group_name in sorted_keys}

        # Default: group by category
        for item in need_items:
            category_name = (item.category or "other").title()
            grouped_need[category_name].append(item)

        def category_sort_key_fn(group_name: str) -> tuple[int, Any]:
            group_name_lower = group_name.lower()
            if group_name_lower in custom_order_map:
                return (0, custom_order_map[group_name_lower])
            return (1, DEPARTMENT_ORDER.get(group_name_lower, 200))

        sorted_keys = sorted(grouped_need.keys(), key=category_sort_key_fn)
        for key in sorted_keys:
            grouped_need[key].sort(key=lambda it: (not it.priority, it.order, it.id))
        return {group_name: grouped_need[group_name] for group_name in sorted_keys}

    @staticmethod
    def resolve_view_mode(
        request: HttpRequest | None,
        requested_mode: str | None = None,
    ) -> str:
        """
        Determine the active shopping workflow mode ('shopping' or 'pantry') from request or session.

        Args:
            request: Optional HttpRequest instance.
            requested_mode: Explicit mode passed as argument.

        Returns:
            Valid mode string ('shopping' or 'pantry').
        """
        mode = requested_mode
        if not mode and request:
            mode = (
                request.GET.get("mode")
                or request.POST.get("mode")
                or request.session.get("shopping_mode", ListMode.SHOPPING)
            )

        if mode not in (ListMode.SHOPPING, ListMode.PANTRY):
            mode = ListMode.SHOPPING

        if request:
            request.session["shopping_mode"] = mode

        return mode
