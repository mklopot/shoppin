"""
Tests for the Shopping List item Priority feature, including:
- ShoppingListItem.priority boolean field
- Quick add priority setting via checkbox and '^' symbol prefix/suffix
- Edit item modal priority checkbox
- Inline priority toggle endpoint
- List organizer grouping by Priority ('Priority Items' vs 'Standard Items')
- Priority items sorted to top within Category and Aisle sections
- Burgundy chevron indicator rendering and styling
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.shopping.models import GroupBy, ItemStatus, ShoppingList, ShoppingListItem, StoreLocation
from apps.shopping.services.list_organizer import ShoppingListOrganizer


@pytest.fixture
def priority_fixture(client):
    from django.contrib.auth import get_user_model

    from apps.core.models import Workspace

    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not admin:
        admin = User.objects.create(username="priority_admin")
    ws = Workspace.objects.first() or Workspace.objects.create(name="Priority WS", owner=admin)
    client.force_login(admin)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    store = StoreLocation.objects.create(name="Safeway Test", chain="safeway")
    s_list = ShoppingList.objects.create(
        name="Priority Test List",
        is_preset=False,
        active_store=store,
        workspace=ws,
        owner=admin,
    )
    # Item 1: Standard item
    item1 = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Whole Milk",
        amount=Decimal("1.00"),
        category="dairy",
        status=ItemStatus.NEED,
        priority=False,
        order=1,
    )
    # Item 2: Priority item
    item2 = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Organic Eggs",
        amount=Decimal("12.00"),
        category="dairy",
        status=ItemStatus.NEED,
        priority=True,
        order=2,
    )
    return {
        "user": admin,
        "workspace": ws,
        "list": s_list,
        "item1": item1,
        "item2": item2,
    }


@pytest.mark.django_db
def test_priority_model_field_default(priority_fixture):
    """ShoppingListItem.priority should default to False and be persistable."""
    s_list = priority_fixture["list"]
    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Apples",
        amount=Decimal("3.00"),
        category="produce",
    )
    assert item.priority is False

    item.priority = True
    item.save()
    item.refresh_from_db()
    assert item.priority is True


@pytest.mark.django_db
def test_add_item_with_priority_checkbox(client, priority_fixture):
    """Quick add form allows setting priority=true via checkbox."""
    response = client.post(
        reverse("shopping:add_item"),
        {
            "name": "Artisan Bread",
            "amount": "1",
            "priority": "true",
        },
    )
    assert response.status_code == 200
    item = ShoppingListItem.objects.get(name="Artisan Bread")
    assert item.priority is True
    # Verify burgundy pill badge is rendered for priority item
    assert b"#800020" in response.content
    assert "Priority".encode("utf-8") in response.content
    assert "🚩".encode("utf-8") in response.content


@pytest.mark.django_db
def test_add_item_with_caret_prefix(client, priority_fixture):
    """Quick add with '^' prefix in item name automatically marks priority and strips caret."""
    response = client.post(
        reverse("shopping:add_item"),
        {
            "name": "^ Coffee Beans",
            "amount": "1",
        },
    )
    assert response.status_code == 200
    item = ShoppingListItem.objects.get(name="Coffee Beans")
    assert item.priority is True


@pytest.mark.django_db
def test_add_item_with_caret_suffix(client, priority_fixture):
    """Quick add with '^' suffix in item name automatically marks priority and strips caret."""
    response = client.post(
        reverse("shopping:add_item"),
        {
            "name": "Dark Chocolate ^",
            "amount": "2",
        },
    )
    assert response.status_code == 200
    item = ShoppingListItem.objects.get(name="Dark Chocolate")
    assert item.priority is True


@pytest.mark.django_db
def test_add_item_with_flag_or_exclamation(client, priority_fixture):
    """Quick add with '🚩' or '!' automatically marks priority and strips trigger."""
    response1 = client.post(
        reverse("shopping:add_item"),
        {
            "name": "🚩 Strawberries",
            "amount": "1",
        },
    )
    assert response1.status_code == 200
    item1 = ShoppingListItem.objects.get(name="Strawberries")
    assert item1.priority is True

    response2 = client.post(
        reverse("shopping:add_item"),
        {
            "name": "! Olive Oil",
            "amount": "1",
        },
    )
    assert response2.status_code == 200
    item2 = ShoppingListItem.objects.get(name="Olive Oil")
    assert item2.priority is True


@pytest.mark.django_db
def test_edit_item_modal_renders_priority_checkbox(client, priority_fixture):
    """Edit item modal should contain the priority checkbox with burgundy chevron."""
    item2 = priority_fixture["item2"]  # priority=True
    response = client.get(reverse("shopping:edit_item", args=[item2.id]))
    assert response.status_code == 200
    assert b'name="priority"' in response.content
    assert b"checked" in response.content
    assert b"#800020" in response.content
    assert "Priority".encode("utf-8") in response.content
    assert "🚩".encode("utf-8") in response.content


@pytest.mark.django_db
def test_edit_item_updates_priority(client, priority_fixture):
    """POSTing to edit_item can toggle priority on and off."""
    item1 = priority_fixture["item1"]  # priority=False
    # Set to priority
    client.post(
        reverse("shopping:edit_item", args=[item1.id]),
        {
            "name": "Whole Milk",
            "amount": "1",
            "category": "dairy",
            "priority": "true",
        },
    )
    item1.refresh_from_db()
    assert item1.priority is True

    # Remove priority
    client.post(
        reverse("shopping:edit_item", args=[item1.id]),
        {
            "name": "Whole Milk",
            "amount": "1",
            "category": "dairy",
        },
    )
    item1.refresh_from_db()
    assert item1.priority is False


@pytest.mark.django_db
def test_toggle_priority_endpoint(client, priority_fixture):
    """POST to toggle_priority flips priority status."""
    item1 = priority_fixture["item1"]
    assert item1.priority is False

    response = client.post(reverse("shopping:toggle_priority", args=[item1.id]))
    assert response.status_code == 200
    item1.refresh_from_db()
    assert item1.priority is True

    response = client.post(reverse("shopping:toggle_priority", args=[item1.id]))
    assert response.status_code == 200
    item1.refresh_from_db()
    assert item1.priority is False


@pytest.mark.django_db
def test_group_by_priority_in_list_organizer(priority_fixture):
    """List organizer separates items into Priority Items and Standard Items."""
    s_list = priority_fixture["list"]
    need_items = list(s_list.items.filter(status=ItemStatus.NEED))
    grouped = ShoppingListOrganizer.group_and_sort_need_items(need_items, GroupBy.PRIORITY, s_list)

    assert "Priority Items" in grouped
    assert "Standard Items" in grouped
    # Priority Items should contain Organic Eggs
    assert [i.name for i in grouped["Priority Items"]] == ["Organic Eggs"]
    # Standard Items should contain Whole Milk
    assert [i.name for i in grouped["Standard Items"]] == ["Whole Milk"]


@pytest.mark.django_db
def test_category_and_aisle_sort_priority_first(priority_fixture):
    """In category grouping, items with priority=True are sorted ahead of non-priority items."""
    s_list = priority_fixture["list"]
    # Both Whole Milk (priority=False, order=1) and Organic Eggs (priority=True, order=2) are in 'dairy'
    need_items = list(s_list.items.filter(status=ItemStatus.NEED))
    grouped = ShoppingListOrganizer.group_and_sort_need_items(need_items, GroupBy.CATEGORY, s_list)

    # In dairy section, Organic Eggs (priority) should be first despite order=2
    dairy_items = grouped["Dairy"]
    assert dairy_items[0].name == "Organic Eggs"
    assert dairy_items[1].name == "Whole Milk"


@pytest.mark.django_db
def test_ui_sort_by_priority_button_and_rendering(client, priority_fixture):
    """Shopping list page includes 'By Priority' button and renders the priority section when active."""
    # Default view
    response = client.get(reverse("shopping:list"))
    assert response.status_code == 200
    assert b"By Priority" in response.content
    assert b"#800020" in response.content

    # Group by Priority view
    response_priority = client.get(reverse("shopping:list") + "?group_by=priority")
    assert response_priority.status_code == 200
    assert b"Priority Items" in response_priority.content
    assert b"Standard Items" in response_priority.content
    assert b"Organic Eggs" in response_priority.content
    assert b"Whole Milk" in response_priority.content

@pytest.mark.django_db
def test_collapsed_preset_lists_card_persists_after_edit(client, priority_fixture):
    """When the preset lists card is collapsed, saving an edit keeps it collapsed."""
    item1 = priority_fixture["item1"]
    # Set collapsed cookie
    client.cookies["preset_lists_open"] = "false"

    response = client.post(
        reverse("shopping:edit_item", args=[item1.id]),
        {
            "name": "Whole Milk (Organic)",
            "amount": "1",
            "category": "dairy",
        },
    )
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'id="preset-lists-body" class="p-2 border-t border-gray-200 flex flex-wrap items-center gap-2 hidden"' in content
    assert 'aria-expanded="false"' in content
