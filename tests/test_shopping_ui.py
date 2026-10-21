from decimal import Decimal

import pytest
from django.urls import reverse

from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, StoreLocation


@pytest.fixture
def active_list():
    store = StoreLocation.objects.create(name="Safeway Corona", chain="safeway")
    s_list = ShoppingList.objects.create(name="Main Shopping List", is_preset=False, active_store=store)
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Bananas",
        amount=Decimal("2.00"),
        category="produce",
        status=ItemStatus.NEED,
        order=1,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Almond Milk",
        amount=Decimal("1.00"),
        category="dairy",
        status=ItemStatus.NEED,
        order=2,
    )
    return s_list


@pytest.mark.django_db
def test_shopping_list_page_loads(client, active_list):
    response = client.get(reverse("shopping:list"))
    assert response.status_code == 200
    assert b"Bananas" in response.content
    assert b"Almond Milk" in response.content
    assert b"To Buy" in response.content


@pytest.mark.django_db
def test_add_item_auto_categorizes(client, active_list):
    response = client.post(
        reverse("shopping:add_item"),
        {"name": "bell pepper", "amount": "2", "brand": ""},
    )
    assert response.status_code == 200
    new_item = active_list.items.get(name="bell pepper")
    assert new_item.amount == Decimal("2.00")
    assert new_item.category == "produce"


@pytest.mark.django_db
def test_add_item_deduplication(client, active_list):
    # Adding bananas again should combine amounts
    client.post(
        reverse("shopping:add_item"),
        {"name": "Bananas", "amount": "3"},
    )
    bananas = active_list.items.filter(name="Bananas")
    assert bananas.count() == 1
    assert bananas.first().amount == Decimal("5.00")  # 2 + 3


@pytest.mark.django_db
def test_item_status_transitions(client, active_list):
    item = active_list.items.get(name="Bananas")
    assert item.status == ItemStatus.NEED

    # 1. Mark as GOT (In Cart)
    client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    item.refresh_from_db()
    assert item.status == ItemStatus.GOT

    # 2. Mark as HAVE (Pantry)
    client.post(reverse("shopping:set_status", args=[item.id, "HAVE"]))
    item.refresh_from_db()
    assert item.status == ItemStatus.HAVE

    # 3. Mark as DONT_NEED (Skipped)
    client.post(reverse("shopping:set_status", args=[item.id, "DONT_NEED"]))
    item.refresh_from_db()
    assert item.status == ItemStatus.DONT_NEED

    # 4. Put back to NEED
    client.post(reverse("shopping:set_status", args=[item.id, "NEED"]))
    item.refresh_from_db()
    assert item.status == ItemStatus.NEED


@pytest.mark.django_db
def test_edit_item_updates_attributes(client, active_list):
    item = active_list.items.get(name="Bananas")
    client.post(
        reverse("shopping:edit_item", args=[item.id]),
        {
            "name": "Organic Bananas",
            "amount": "6",
            "amount_unit": "pieces",
            "category": "produce",
            "aisle": "Aisle 1",
            "brand": "Chiquita",
            "vendor": "Safeway",
        },
    )
    item.refresh_from_db()
    assert item.name == "Organic Bananas"
    assert item.amount == Decimal("6.00")
    assert item.amount_unit == "pieces"
    assert item.brand == "Chiquita"
    assert item.aisle == "Aisle 1"


@pytest.mark.django_db
def test_clear_completed_cart_items(client, active_list):
    item1 = active_list.items.get(name="Bananas")
    item1.status = ItemStatus.GOT
    item1.save()

    client.post(reverse("shopping:clear_completed"))
    assert not active_list.items.filter(name="Bananas").exists()
    assert active_list.items.filter(name="Almond Milk").exists()


@pytest.mark.django_db
def test_item_purpose_handling(client, active_list):
    # 1. Blank purpose defaults to "one-time purchase"
    client.post(
        reverse("shopping:add_item"),
        {"name": "Paper Towels", "amount": "1"},
    )
    towel = active_list.items.get(name="Paper Towels")
    assert towel.purpose == "one-time purchase"

    # 2. Custom purpose provided
    client.post(
        reverse("shopping:add_item"),
        {"name": "Birthday Candles", "amount": "1", "purpose": "Ezra Birthday"},
    )
    candles = active_list.items.get(name="Birthday Candles")
    assert candles.purpose == "Ezra Birthday"

    # 3. Editing purpose
    client.post(
        reverse("shopping:edit_item", args=[towel.id]),
        {
            "name": towel.name,
            "amount": towel.amount,
            "amount_unit": towel.amount_unit,
            "purpose": "Cleaning Supplies",
        },
    )
    towel.refresh_from_db()
    assert towel.purpose == "Cleaning Supplies"


@pytest.mark.django_db
def test_item_transitions_and_toast_notifications(client, active_list):
    item = active_list.items.get(name="Bananas")

    # 1. Transition to GOT: checks toast notification and view-transition-name styling
    res = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "Moved &#x27;Bananas&#x27; to Cart" in content or "Moved 'Bananas' to Cart" in content
    assert 'hx-swap-oob="beforeend"' in content
    assert f"view-transition-name: item-row-{item.id}" in content

    # 2. Add item toast notification
    res = client.post(reverse("shopping:add_item"), {"name": "Sourdough", "amount": "1"})
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "+ Added &#x27;Sourdough&#x27; to shopping list" in content or "+ Added 'Sourdough' to shopping list" in content

    # 3. Delete item toast notification
    res = client.post(reverse("shopping:delete_item", args=[item.id]))
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "Deleted &#x27;Bananas&#x27;" in content or "Deleted 'Bananas'" in content


@pytest.mark.django_db
def test_reorder_sections_custom_order(client, active_list):
    # active_list has Bananas in produce and Almond Milk in dairy.
    # By default, Produce comes before Dairy in DEPARTMENT_ORDER.
    res_initial = client.get(reverse("shopping:list"))
    content_initial = res_initial.content.decode("utf-8")
    produce_pos = content_initial.find("Produce")
    dairy_pos = content_initial.find("Dairy")
    assert produce_pos < dairy_pos

    # Now drag Dairy above Produce:
    res = client.post(
        reverse("shopping:reorder_sections"),
        {"group_by": "category", "group_names[]": ["Dairy", "Produce"]},
    )
    assert res.status_code == 204

    active_list.refresh_from_db()
    assert active_list.custom_section_order.get("category") == ["Dairy", "Produce"]

    # Verify that the shopping list page now renders Dairy before Produce:
    res_after = client.get(reverse("shopping:list"))
    content_after = res_after.content.decode("utf-8")
    new_produce_pos = content_after.find("Produce")
    new_dairy_pos = content_after.find("Dairy")
    assert new_dairy_pos < new_produce_pos


@pytest.mark.django_db
def test_to_buy_section_styling_and_drag_handles(client, active_list):
    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    content = res.content.decode("utf-8")

    # Section drag handles present
    assert "section-drag-handle" in content
    assert "section-group-block" in content

    # Horizontal line under section names removed (border-b-2 border-gray-900 removed)
    assert "border-b-2 border-gray-900" not in content

    # Redundant sort order text removed
    assert "Sorted by" not in content

    # Combined header with title and store select
    assert "Shopping List" in content
    assert "name=\"store_id\"" in content
