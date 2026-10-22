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

    # 1. Transition to GOT: checks toast notification, light transparent styling, and view-transition-name
    res = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "Moved &#x27;Bananas&#x27; to Cart" in content or "Moved 'Bananas' to Cart" in content
    assert 'hx-swap-oob="beforeend"' in content
    assert "bg-white/90" in content
    assert "backdrop-blur-sm" in content
    assert "bg-gray-950" not in content
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

    # Vertical line to the left of category removed
    assert "border-l-2" not in content

    # Redundant sort order text removed
    assert "Sorted by" not in content

    # Combined header with title and store select
    assert "Shopping List" in content
    assert "name=\"store_id\"" in content

    # Item remove/delete buttons removed from UI in favor of Skip
    assert "delete_item" not in content


@pytest.mark.django_db
def test_category_and_aisle_pulldown_and_custom_typing(client, active_list):
    item = active_list.items.get(name="Bananas")

    # 1. Edit modal should render datalists with known categories and known aisles
    res_modal = client.get(reverse("shopping:edit_item", args=[item.id]))
    assert res_modal.status_code == 200
    modal_content = res_modal.content.decode("utf-8")

    assert 'list="category-datalist"' in modal_content
    assert 'id="category-datalist"' in modal_content
    assert '<option value="Produce">' in modal_content
    assert '<option value="Dairy">' in modal_content

    assert 'list="aisle-datalist"' in modal_content
    assert 'id="aisle-datalist"' in modal_content
    assert '<option value="Aisle 1">' in modal_content or '<option value="Produce">' in modal_content

    # 2. Saving a new typed category and aisle (not in datalist initially) works
    res_save = client.post(
        reverse("shopping:edit_item", args=[item.id]),
        {
            "name": item.name,
            "amount": str(item.amount),
            "amount_unit": item.amount_unit,
            "category": "Gourmet Specialty",
            "aisle": "Aisle 99",
        },
    )
    assert res_save.status_code == 200
    item.refresh_from_db()
    assert item.category == "Gourmet Specialty"
    assert item.aisle == "Aisle 99"

    # 3. Next modal visit now includes the newly typed category and aisle in the pull-down list!
    res_modal_2 = client.get(reverse("shopping:edit_item", args=[item.id]))
    modal_content_2 = res_modal_2.content.decode("utf-8")
    assert '<option value="Gourmet Specialty">' in modal_content_2
    assert '<option value="Aisle 99">' in modal_content_2


@pytest.mark.django_db
def test_shopping_and_pantry_mode_switching_and_persistence(client, active_list):
    # Add a pantry item (status HAVE) to verify details open/close behavior
    ShoppingListItem.objects.create(
        shopping_list=active_list,
        name="Olive Oil",
        amount=Decimal("1.00"),
        category="pantry",
        status=ItemStatus.HAVE,
        order=10,
    )

    # 1. Default load: Shopping (In Store) Mode
    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    content = res.content.decode("utf-8")

    # In Store mode toggle is visually higher up than Store selector and sort order
    in_store_pos = content.find("In Store")
    store_pos = content.find("Store:")
    sort_pos = content.find("By Category")
    assert in_store_pos < store_pos < sort_pos

    assert "In Store" in content
    assert "Pantry Check" in content
    assert "Pantry Check Mode:" not in content

    # Under To Buy, we should see "Got" (with white background, not black) and "⏭ Skip", but NOT "Have"
    to_buy_section = content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🛒 Got" in to_buy_section
    assert "⏭ Skip" in to_buy_section
    assert "🏠 Have" not in to_buy_section
    # Got button should NOT have a black background
    assert "bg-gray-800 text-white px-3 py-1 text-xs font-semibold" not in to_buy_section

    # The pantry details section should be collapsed (not open)
    assert "<details open class=\"border border-amber-300" not in content
    assert "Already Have / Skipped" in content

    # 2. Switch to Pantry Check Mode via query param ?mode=pantry
    res_pantry = client.get(reverse("shopping:list") + "?mode=pantry")
    assert res_pantry.status_code == 200
    pantry_content = res_pantry.content.decode("utf-8")

    # Banner is visible
    assert "Pantry Check Mode:" in pantry_content
    assert "Ready to shop &rarr;" in pantry_content

    # Under To Buy in Pantry mode:
    # We see Have, ⏭ Skip, and 📋 Need buttons, but NOT 🛒 Got!
    pantry_to_buy = pantry_content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🏠 Have" in pantry_to_buy
    assert "⏭ Skip" in pantry_to_buy
    assert "📋 Need" in pantry_to_buy
    assert "🛒 Got" not in pantry_to_buy

    # The pantry details section is automatically opened
    assert "<details open" in pantry_content

    # 3. Session persistence: Subsequent request without ?mode still remembers pantry mode
    res_session = client.get(reverse("shopping:list"))
    session_content = res_session.content.decode("utf-8")
    assert "Pantry Check Mode:" in session_content
    session_to_buy = session_content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🏠 Have" in session_to_buy
    assert "⏭ Skip" in session_to_buy
    assert "🛒 Got" not in session_to_buy

    # 4. Check/Confirm Need on an item (similar to legacy lock, but reversible)
    banana_item = active_list.items.get(name="Bananas")
    res_lock = client.post(reverse("shopping:toggle_lock", args=[banana_item.id]))
    assert res_lock.status_code == 200
    banana_item.refresh_from_db()
    assert banana_item.locked is True

    # When locked/confirmed needed:
    # - Shows visual badge 📋 Need
    # - Hides the "🏠 Have" button for this item
    # - Button shows "📋 Need"
    lock_content = res_lock.content.decode("utf-8")
    banana_row = [row for row in lock_content.split('id="item-row-') if f'item-row-{banana_item.id}' in f'item-row-{row}'][0]
    assert "📋 Need" in banana_row
    assert "🏠 Have" not in banana_row

    # Toggling lock again reverses it cleanly
    res_unlock = client.post(reverse("shopping:toggle_lock", args=[banana_item.id]))
    assert res_unlock.status_code == 200
    banana_item.refresh_from_db()
    assert banana_item.locked is False
    unlock_content = res_unlock.content.decode("utf-8")
    banana_row_unlocked = [row for row in unlock_content.split('id="item-row-') if f'item-row-{banana_item.id}' in f'item-row-{row}'][0]
    assert "🏠 Have" in banana_row_unlocked

    # 5. Marking an item as HAVE in Pantry mode moves it to Already Have
    res_mark = client.post(reverse("shopping:set_status", args=[banana_item.id, "HAVE"]))
    assert res_mark.status_code == 200
    banana_item.refresh_from_db()
    assert banana_item.status == ItemStatus.HAVE
    # Verify Already Have section has Need, but NO Got button
    pantry_section = res_mark.content.decode("utf-8").split("Already Have / Skipped")[1]
    assert "📋 Need" in pantry_section
    assert "🛒 Got" not in pantry_section

    # 6. Move an item to GOT and verify that the Got section has Need, but NO Have and NO Skip
    milk_item = active_list.items.get(name="Almond Milk")
    res_got = client.post(reverse("shopping:set_status", args=[milk_item.id, "GOT"]))
    assert res_got.status_code == 200
    got_content = res_got.content.decode("utf-8")
    got_section = got_content.split("Purchased in cart")[1].split("Already Have / Skipped")[0]
    assert "📋 Need" in got_section
    assert "🏠 Have" not in got_section
    assert "Skip" not in got_section
    assert "⏭" not in got_section

    # 7. Move an item back to NEED and switch back to In Store mode via ?mode=shopping
    client.post(reverse("shopping:set_status", args=[banana_item.id, "NEED"]))
    res_shopping = client.get(reverse("shopping:list") + "?mode=shopping")
    assert res_shopping.status_code == 200
    shopping_content = res_shopping.content.decode("utf-8")
    assert "Pantry Check Mode:" not in shopping_content
    shopping_to_buy = shopping_content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🏠 Have" not in shopping_to_buy
    assert "⏭ Skip" in shopping_to_buy
    assert "🛒 Got" in shopping_to_buy
