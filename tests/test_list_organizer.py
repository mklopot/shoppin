"""
Unit tests for the ShoppingListOrganizer service, ListMode/GroupBy enums, and response helpers.
"""

from decimal import Decimal

import pytest
from django.test import RequestFactory

from apps.shopping.models import (
    GroupBy,
    ItemStatus,
    ListMode,
    ShoppingList,
    ShoppingListItem,
    StoreLocation,
)
from apps.shopping.services.list_organizer import ShoppingListOrganizer
from apps.shopping.views import render_list_response


@pytest.fixture
def sample_shopping_list(db):
    """Fixture providing a populated test shopping list."""
    store = StoreLocation.objects.create(name="King Soopers #100", chain="kroger")
    s_list = ShoppingList.objects.create(name="Test List", active_store=store)

    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Apples",
        amount=Decimal("3.00"),
        category="produce",
        aisle="Produce Stand",
        status=ItemStatus.NEED,
        order=1,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Milk",
        amount=Decimal("1.00"),
        category="dairy",
        aisle="Aisle 1",
        status=ItemStatus.NEED,
        order=2,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Bread",
        amount=Decimal("1.00"),
        category="bakery",
        aisle="Bakery",
        status=ItemStatus.GOT,
        order=3,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Olive Oil",
        amount=Decimal("1.00"),
        category="oil",
        aisle="Aisle 4",
        status=ItemStatus.HAVE,
        order=4,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Soda",
        amount=Decimal("2.00"),
        category="beverages",
        aisle="Aisle 7",
        status=ItemStatus.DONT_NEED,
        order=5,
    )
    return s_list


def test_partition_items(sample_shopping_list):
    """Test partitioning shopping list items by lifecycle status."""
    items = sample_shopping_list.items.all()
    need_items, got_items, pantry_items = ShoppingListOrganizer.partition_items(items)

    assert len(need_items) == 2
    assert {item.name for item in need_items} == {"Apples", "Milk"}

    assert len(got_items) == 1
    assert got_items[0].name == "Bread"

    assert len(pantry_items) == 2
    assert {item.name for item in pantry_items} == {"Olive Oil", "Soda"}


def test_group_and_sort_by_category(sample_shopping_list):
    """Test grouping need items by supermarket department category."""
    items = list(sample_shopping_list.items.filter(status=ItemStatus.NEED))
    grouped = ShoppingListOrganizer.group_and_sort_need_items(
        need_items=items,
        group_by=GroupBy.CATEGORY,
        shopping_list=sample_shopping_list,
    )

    # Produce (order 10) should sort before Dairy (order 95)
    keys = list(grouped.keys())
    assert keys == ["Produce", "Dairy"]
    assert grouped["Produce"][0].name == "Apples"
    assert grouped["Dairy"][0].name == "Milk"


def test_group_and_sort_by_aisle(sample_shopping_list):
    """Test grouping need items by physical store aisle."""
    items = list(sample_shopping_list.items.filter(status=ItemStatus.NEED))
    grouped = ShoppingListOrganizer.group_and_sort_need_items(
        need_items=items,
        group_by=GroupBy.AISLE,
        shopping_list=sample_shopping_list,
    )

    # Produce Stand (perimeter entrance 10) sorts before Aisle 1 (numbered 100+1)
    keys = list(grouped.keys())
    assert keys == ["Produce Stand", "Aisle 1"]


def test_resolve_view_mode_defaults():
    """Test resolving mode when no parameters or session are supplied."""
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {}

    mode = ShoppingListOrganizer.resolve_view_mode(request)
    assert mode == ListMode.SHOPPING
    assert request.session["shopping_mode"] == ListMode.SHOPPING


def test_resolve_view_mode_from_request():
    """Test resolving mode from GET query parameter."""
    factory = RequestFactory()
    request = factory.get("/?mode=pantry")
    request.session = {}

    mode = ShoppingListOrganizer.resolve_view_mode(request)
    assert mode == ListMode.PANTRY
    assert request.session["shopping_mode"] == ListMode.PANTRY


def test_render_list_response_partial_vs_full(sample_shopping_list):
    """Test standardized response helper handles both partial and full templates."""
    factory = RequestFactory()

    # 1. Action / Force partial request
    req1 = factory.post("/add-item/")
    resp1 = render_list_response(
        req1,
        context={"shopping_list": sample_shopping_list},
        toast_message="Added test item",
        force_partial=True,
    )
    assert resp1.status_code == 200
    assert b"Added test item" in resp1.content

    # 2. Browser full-page GET request
    req2 = factory.get("/")
    resp2 = render_list_response(
        req2,
        context={"shopping_list": sample_shopping_list},
        force_partial=False,
    )
    assert resp2.status_code == 200
    assert b"<!DOCTYPE html>" in resp2.content


def test_alphabetical_sorting_within_categories(db):
    """Test that items within the same category are sorted alphabetically by name."""
    s_list = ShoppingList.objects.create(name="Alphabetical Category Test")
    ShoppingListItem.objects.create(shopping_list=s_list, name="Zucchini", category="produce", status=ItemStatus.NEED)
    ShoppingListItem.objects.create(shopping_list=s_list, name="Apples", category="produce", status=ItemStatus.NEED)
    ShoppingListItem.objects.create(shopping_list=s_list, name="Bananas", category="produce", status=ItemStatus.NEED)

    items = list(s_list.items.all())
    grouped = ShoppingListOrganizer.group_and_sort_need_items(
        need_items=items,
        group_by=GroupBy.CATEGORY,
        shopping_list=s_list,
    )
    produce_names = [it.name for it in grouped["Produce"]]
    assert produce_names == ["Apples", "Bananas", "Zucchini"]


def test_alphabetical_sorting_within_aisles_and_priorities(db):
    """Test that items within the same aisle and priority levels are sorted alphabetically."""
    store = StoreLocation.objects.create(name="Store A")
    s_list = ShoppingList.objects.create(name="Aisle Test", active_store=store)

    ShoppingListItem.objects.create(shopping_list=s_list, name="Zesta Crackers", aisle="Aisle 3", status=ItemStatus.NEED, priority=False)
    ShoppingListItem.objects.create(shopping_list=s_list, name="Animal Crackers", aisle="Aisle 3", status=ItemStatus.NEED, priority=False)
    ShoppingListItem.objects.create(shopping_list=s_list, name="Oreos", aisle="Aisle 3", status=ItemStatus.NEED, priority=True)
    ShoppingListItem.objects.create(shopping_list=s_list, name="Chips Ahoy", aisle="Aisle 3", status=ItemStatus.NEED, priority=True)

    items = list(s_list.items.all())
    grouped = ShoppingListOrganizer.group_and_sort_need_items(
        need_items=items,
        group_by=GroupBy.AISLE,
        shopping_list=s_list,
    )
    aisle3_names = [it.name for it in grouped["Aisle 3"]]
    # Priority items first alphabetically (Chips Ahoy, Oreos), then standard items alphabetically (Animal Crackers, Zesta Crackers)
    assert aisle3_names == ["Chips Ahoy", "Oreos", "Animal Crackers", "Zesta Crackers"]

