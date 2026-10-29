"""
Integration and UI tests for shopping list views, HTMX interactions, and styling.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, StoreLocation


@pytest.fixture
def active_list(client):
    from django.contrib.auth import get_user_model

    from apps.core.models import Workspace
    User = get_user_model()
    admin = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not admin:
        admin = User.objects.create(username="admin_fixture")
    ws = Workspace.objects.first() or Workspace.objects.create(name="Home", owner=admin)
    client.force_login(admin)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    store = StoreLocation.objects.create(name="Safeway Corona", chain="safeway")
    s_list = ShoppingList.objects.create(
        name="Main Shopping List",
        is_preset=False,
        active_store=store,
        workspace=ws,
        owner=admin,
    )
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
def test_add_one_pint_plus_one_pint_makes_a_quart(client, active_list):
    # Add 1 pint of cream
    client.post(
        reverse("shopping:add_item"),
        {"name": "Heavy Cream", "amount": "1 pint"},
    )
    cream = active_list.items.get(name="Heavy Cream")
    assert cream.amount == Decimal("1.00")
    assert cream.amount_unit == "pint"

    # Add another 1 pint of cream -> should convert to 1 quart!
    client.post(
        reverse("shopping:add_item"),
        {"name": "Heavy Cream", "amount": "1 pint"},
    )
    cream.refresh_from_db()
    assert cream.amount == Decimal("1.00")
    assert cream.amount_unit == "quart"
    assert cream.amount_display == "1"
    assert cream.unit_display == "quart"


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
    assert item.locked is True


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
def test_no_clear_cart_button_or_endpoint(client, active_list):
    item1 = active_list.items.get(name="Bananas")
    item1.status = ItemStatus.GOT
    item1.save()

    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    assert b"Clear Cart" not in res.content
    assert b"clear_completed" not in res.content


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
    assert "You moved &#x27;Bananas&#x27; to Cart" in content or "You moved 'Bananas' to Cart" in content
    assert 'hx-swap-oob="beforeend"' in content
    assert "bg-white/90" in content
    assert "backdrop-blur-sm" in content
    assert "bg-gray-950" not in content
    assert f"view-transition-name: item-row-{item.id}" in content

    # 2. Add item toast notification
    res = client.post(reverse("shopping:add_item"), {"name": "Sourdough", "amount": "1"})
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "You added &#x27;Sourdough&#x27; to the shopping list" in content or "You added 'Sourdough' to the shopping list" in content

    # 3. Delete item toast notification
    res = client.post(reverse("shopping:delete_item", args=[item.id]))
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    assert "You deleted &#x27;Bananas&#x27;" in content or "You deleted 'Bananas'" in content


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
    # Add a pantry item (status HAVE) to verify Already Have rendering
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

    # Shopping List and Pantry Check navigation tabs on top are visually higher up than Store selector and sort order
    shopping_tab_pos = content.find("Shopping List")
    pantry_tab_pos = content.find("Pantry Check")
    store_pos = content.find("Store:")
    sort_pos = content.find("By Category")
    assert shopping_tab_pos < pantry_tab_pos < store_pos < sort_pos

    assert "Shopping List" in content
    assert "Pantry Check" in content
    assert "Pantry Check Mode:" not in content

    # Under To Buy, we should see "Got" (with white background, not black) and "⏭ Skip", but NOT "Have"
    to_buy_section = content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🛒 Got" in to_buy_section
    assert "⏭ Skip" in to_buy_section
    assert "🏠 Have" not in to_buy_section
    # Got button should NOT have a black background
    assert "bg-gray-800 text-white px-3 py-1 text-xs font-semibold" not in to_buy_section

    # The Already Have / Skipped section is permanently visible and non-collapsible
    assert "<details" not in content
    assert "Already Have / Skipped" in content

    # 2. Switch to Pantry Check Mode via query param ?mode=pantry or dedicated /pantry-check/ route
    res_direct = client.get(reverse("shopping:pantry_check"))
    assert res_direct.status_code == 200
    assert "Pantry Check Mode:" in res_direct.content.decode("utf-8")

    res_pantry = client.get(reverse("shopping:list") + "?mode=pantry")
    assert res_pantry.status_code == 200
    pantry_content = res_pantry.content.decode("utf-8")

    # Banner is visible
    assert "Pantry Check Mode:" in pantry_content
    assert "Ready to shop &rarr;" in pantry_content

    # Under To Buy in Pantry mode:
    # We see Have, 📋 Need, and ⏭ Skip buttons, but NOT 🛒 Got!
    pantry_to_buy = pantry_content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "🏠 Have" in pantry_to_buy
    assert "📋 Need" in pantry_to_buy
    assert "⏭ Skip" in pantry_to_buy
    assert pantry_to_buy.find("📋 Need") < pantry_to_buy.find("⏭ Skip")
    assert "🛒 Got" not in pantry_to_buy

    # The Already Have section is always visible (non-collapsible) in pantry mode too
    assert "<details" not in pantry_content
    assert "Already Have / Skipped" in pantry_content

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
    assert "You set &#x27;Bananas&#x27; to &quot;needed&quot;" in lock_content or "You set 'Bananas' to \"needed\"" in lock_content
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
    # Verify Already Have section has Need, but NO Got button and NO Skip button
    pantry_section = res_mark.content.decode("utf-8").split("Already Have / Skipped")[1]
    assert "📋 Need" in pantry_section
    assert "🛒 Got" not in pantry_section
    assert "Skip" not in pantry_section

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


@pytest.mark.django_db
def test_item_status_changed_at_timestamp_display(client, active_list):
    import datetime

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    User = get_user_model()
    alice = User.objects.create_user(username="Alice", password="password123")

    # Create an item with a status_changed_at in the past
    past_date = timezone.now() - datetime.timedelta(days=5)
    item = ShoppingListItem.objects.create(
        shopping_list=active_list,
        name="Granola",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
        status_changed_at=past_date,
        order=20,
    )

    # 1. Page load displays mm/dd format without user attribution when workspace is not shared
    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    expected_past_date_str = timezone.localtime(past_date).strftime("%m/%d")
    content = res.content.decode("utf-8")
    assert expected_past_date_str in content
    # When workspace is not shared, attribution field must be empty
    assert f"unknown {expected_past_date_str}" not in content
    assert f"You {expected_past_date_str}" not in content
    # Verify non-fixed-width and italics styling
    assert 'class="ml-1.5 text-gray-400 italic text-xs select-none"' in content

    # 2. Changing status as authenticated admin user in unshared workspace shows only date
    res_got = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert res_got.status_code == 200
    item.refresh_from_db()
    assert item.status_changed_by is not None
    today_str = timezone.localtime(timezone.now()).strftime("%m/%d")
    got_content = res_got.content.decode("utf-8")
    got_section = got_content.split("Purchased in cart")[1].split("Already Have / Skipped")[0]
    assert today_str in got_section
    assert f"{item.status_changed_by_name} {today_str}" not in got_section
    assert f"You {today_str}" not in got_section
    assert "Granola" in got_section

    # 3. Sharing workspace with another user (Alice) activates user attribution using first name
    if active_list.workspace:
        from apps.core.models import WorkspaceMember, WorkspaceRole
        WorkspaceMember.objects.update_or_create(
            workspace=active_list.workspace,
            user=alice,
            defaults={"role": WorkspaceRole.EDITOR},
        )
    client.force_login(alice)
    res_have = client.post(reverse("shopping:set_status", args=[item.id, "HAVE"]))
    assert res_have.status_code == 200
    item.refresh_from_db()
    assert item.status_changed_by == alice
    assert item.status_changed_by_name == "Alice"
    assert item.is_shared is True
    assert item.changed_by_display == "Alice"
    have_content = res_have.content.decode("utf-8")
    have_section = have_content.split("Already Have / Skipped")[1]
    assert f"Alice {today_str}" in have_section
    assert "Granola" in have_section


@pytest.mark.django_db
def test_in_store_location_not_shown_in_got_and_already_have(client, active_list):
    # Bananas has aisle set to "Aisle 1"
    item = active_list.items.get(name="Bananas")
    item.aisle = "Aisle 1"
    item.save(update_fields=["aisle"])

    # 1. Under "To Buy", the in-store location "📍 Aisle 1" IS shown
    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    content = res.content.decode("utf-8")
    to_buy_section = content.split("To Buy")[1].split("Already Have / Skipped")[0]
    assert "📍 Aisle 1" in to_buy_section

    # 2. When moved to GOT, neither "📍 Aisle 1" nor section name "(Produce)" is shown in Got section
    res_got = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert res_got.status_code == 200
    got_content = res_got.content.decode("utf-8")
    got_section = got_content.split("Purchased in cart")[1].split("Already Have / Skipped")[0]
    assert "Bananas" in got_section
    assert "📍 Aisle 1" not in got_section
    assert "(Produce)" not in got_section

    # 3. When moved to HAVE, neither "📍 Aisle 1" nor section name "(Produce)" is shown in Already Have section
    res_have = client.post(reverse("shopping:set_status", args=[item.id, "HAVE"]))
    assert res_have.status_code == 200
    have_content = res_have.content.decode("utf-8")
    have_section = have_content.split("Already Have / Skipped")[1]
    assert "Bananas" in have_section
    assert "📍 Aisle 1" not in have_section
    assert "(Produce)" not in have_section


@pytest.mark.django_db
def test_in_store_view_shows_pantry_check_confirmation_status(client, active_list):
    """Verify that in the In Store view, only unconfirmed items show a subtle 'pantry check needed' tag."""
    bananas = active_list.items.get(name="Bananas")
    milk = active_list.items.get(name="Almond Milk")

    # Mark Bananas as confirmed needed (locked=True), Milk as unconfirmed (locked=False)
    bananas.locked = True
    bananas.save(update_fields=["locked"])
    milk.locked = False
    milk.save(update_fields=["locked"])

    # 1. Fetch In Store view (mode=shopping)
    res = client.get(reverse("shopping:list") + "?mode=shopping")
    assert res.status_code == 200
    content = res.content.decode("utf-8")

    # Summary in To Buy header shows unconfirmed count
    assert "1 pantry check needed" in content

    # Confirmed item (Bananas) has NO confirmed tag
    assert "✓ Confirmed" not in content

    # Unconfirmed item (Almond Milk) has subtle 'pantry check needed' tag
    assert ">pantry check needed<" in content

    # 2. Toggle lock on Milk to confirm it
    res_toggle = client.post(reverse("shopping:toggle_lock", args=[milk.id]) + "?mode=shopping")
    assert res_toggle.status_code == 200
    milk.refresh_from_db()
    assert milk.locked is True
    toggle_content = res_toggle.content.decode("utf-8")
    # Now both are confirmed, so no 'pantry check needed' tags or header alerts remain
    assert ">pantry check needed<" not in toggle_content
    assert "pantry check needed</span>" not in toggle_content


@pytest.mark.django_db
def test_edit_item_triggers_combine_and_resets_confirmation(client, active_list):
    """Verify editing an item to match another item combines them and resets confirmation status."""
    bananas = active_list.items.get(name="Bananas")
    milk = active_list.items.get(name="Almond Milk")

    # Confirm Bananas
    bananas.locked = True
    bananas.amount = Decimal("2.00")
    bananas.save(update_fields=["locked", "amount"])

    milk.amount = Decimal("3.00")
    milk.save(update_fields=["amount"])

    # Edit milk to also be "Bananas"
    res = client.post(
        reverse("shopping:edit_item", args=[milk.id]),
        {
            "name": "Bananas",
            "amount": "3",
            "amount_unit": "",
            "category": "produce",
            "brand": "",
            "vendor": "",
            "purpose": "snack",
        },
    )
    assert res.status_code == 200

    # The two items should now be combined into 1 Bananas item with amount 5
    items = active_list.items.filter(name="Bananas")
    assert items.count() == 1
    combined = items.first()
    assert combined.amount == Decimal("5.00")
    # Because it was combined, its confirmation status should be reset to False (not confirmed)
    assert combined.locked is False


@pytest.mark.django_db
def test_edit_item_amount_increase_resets_confirmation(client, active_list):
    """Verify that editing an item to increase its amount resets confirmation status."""
    bananas = active_list.items.get(name="Bananas")
    bananas.amount = Decimal("2.00")
    bananas.locked = True
    bananas.save(update_fields=["amount", "locked"])

    # Edit bananas to increase amount from 2 to 6
    res = client.post(
        reverse("shopping:edit_item", args=[bananas.id]),
        {
            "name": "Bananas",
            "amount": "6",
            "amount_unit": "",
            "category": "produce",
            "brand": "",
            "vendor": "",
            "purpose": "daily",
        },
    )
    assert res.status_code == 200
    bananas.refresh_from_db()
    assert bananas.amount == Decimal("6.00")
    assert bananas.locked is False


@pytest.mark.django_db
def test_edit_item_amount_decrease_preserves_confirmation(client, active_list):
    """Verify that editing an item to decrease its amount keeps its confirmed status."""
    bananas = active_list.items.get(name="Bananas")
    bananas.amount = Decimal("4.00")
    bananas.locked = True
    bananas.save(update_fields=["amount", "locked"])

    # Edit bananas to decrease amount from 4 to 2
    res = client.post(
        reverse("shopping:edit_item", args=[bananas.id]),
        {
            "name": "Bananas",
            "amount": "2",
            "amount_unit": "",
            "category": "produce",
            "brand": "",
            "vendor": "",
            "purpose": "daily",
        },
    )
    assert res.status_code == 200
    bananas.refresh_from_db()
    assert bananas.amount == Decimal("2.00")
    assert bananas.locked is True


@pytest.mark.django_db
def test_pantry_check_navigation_tab(client, active_list):
    """Verify that Pantry Check navigation is in its own top tab next to Shopping List."""
    # 1. Main Shopping List page
    res_shop = client.get(reverse("shopping:list") + "?mode=shopping")
    assert res_shop.status_code == 200
    shop_html = res_shop.content.decode("utf-8")

    # Both tabs exist in header
    assert "Shopping List" in shop_html
    assert "Pantry Check" in shop_html
    # Dedicated toggle is removed
    assert "🛒 In Store" not in shop_html
    # Shopping List tab is active (font-semibold, border-b-2), Pantry Check is inactive (font-medium)
    assert 'href="/?mode=shopping"' in shop_html
    assert 'href="/pantry-check/"' in shop_html
    assert 'font-semibold text-gray-900 border-b-2 border-gray-800' in shop_html
    assert 'font-medium text-gray-600 hover:text-gray-900' in shop_html

    # 2. Pantry Check route
    res_pantry = client.get(reverse("shopping:pantry_check"))
    assert res_pantry.status_code == 200
    pantry_html = res_pantry.content.decode("utf-8")

    # Pantry Check tab is active (font-semibold, border-b-2), Shopping List is inactive (font-medium)
    assert 'href="/pantry-check/"' in pantry_html
    assert 'href="/?mode=shopping"' in pantry_html
    assert 'font-semibold text-gray-900 border-b-2 border-gray-800' in pantry_html
    assert 'font-medium text-gray-600 hover:text-gray-900' in pantry_html
    # Helper banner is shown
    assert "Pantry Check Mode:" in pantry_html
    assert "Ready to shop &rarr;" in pantry_html


@pytest.mark.django_db
def test_need_button_from_got_or_pantry_confirms_item_status(client, active_list):
    """
    Pressing 'need' on an item from the 'got' or 'already have/skipped' section
    must mark the item as confirmed (locked=True), so it never appears with 'not confirmed' status.
    """
    # Ensure all existing items are confirmed
    active_list.items.all().update(locked=True)

    # 1. Unconfirmed item in GOT (In Cart)
    item_got = ShoppingListItem.objects.create(
        shopping_list=active_list,
        name="Cart Item",
        amount=Decimal("1.00"),
        category="dairy",
        status=ItemStatus.GOT,
        locked=False,
        order=10,
    )
    res_need = client.post(
        reverse("shopping:set_status", args=[item_got.id, "NEED"]) + "?mode=shopping"
    )
    assert res_need.status_code == 200
    item_got.refresh_from_db()
    assert item_got.status == ItemStatus.NEED
    assert item_got.locked is True

    # Ensure HTML response doesn't show "pantry check needed" badge or count for Cart Item
    content = res_need.content.decode("utf-8")
    assert ">pantry check needed<" not in content
    assert "pantry check needed</span>" not in content

    # 2. Unconfirmed item in HAVE (Already Have / Pantry)
    item_have = ShoppingListItem.objects.create(
        shopping_list=active_list,
        name="Pantry Item",
        amount=Decimal("1.00"),
        category="bakery",
        status=ItemStatus.HAVE,
        locked=False,
        order=11,
    )
    res_have_need = client.post(
        reverse("shopping:set_status", args=[item_have.id, "NEED"]) + "?mode=shopping"
    )
    assert res_have_need.status_code == 200
    item_have.refresh_from_db()
    assert item_have.status == ItemStatus.NEED
    assert item_have.locked is True

    content_have = res_have_need.content.decode("utf-8")
    assert ">pantry check needed<" not in content_have
    assert "pantry check needed</span>" not in content_have

    # 3. Unconfirmed item in DONT_NEED (Skipped)
    item_skip = ShoppingListItem.objects.create(
        shopping_list=active_list,
        name="Skipped Item",
        amount=Decimal("1.00"),
        category="snacks",
        status=ItemStatus.DONT_NEED,
        locked=False,
        order=12,
    )
    res_skip_need = client.post(
        reverse("shopping:set_status", args=[item_skip.id, "NEED"]) + "?mode=shopping"
    )
    assert res_skip_need.status_code == 200
    item_skip.refresh_from_db()
    assert item_skip.status == ItemStatus.NEED
    assert item_skip.locked is True

    content_skip = res_skip_need.content.decode("utf-8")
    assert ">pantry check needed<" not in content_skip
    assert "pantry check needed</span>" not in content_skip


@pytest.mark.django_db
def test_attribution_shows_first_name_and_omitted_when_unshared(client):
    """
    Test user attribution:
    1. Should list the first name of the user, not the full username.
    2. If the workspace is not shared, it should not show anything in that field.
    """
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from apps.core.models import Workspace, WorkspaceMember, WorkspaceRole

    User = get_user_model()
    owner = User.objects.create_user(username="michael.klopot", first_name="Mike", last_name="Klopot")
    collaborator = User.objects.create_user(username="carol.danvers", first_name="Carol", last_name="Danvers")

    ws = Workspace.objects.create(name="Mike's Kitchen", owner=owner)
    s_list = ShoppingList.objects.create(name="Grocery List", workspace=ws, owner=owner)

    client.force_login(owner)

    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Sourdough Loaf",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
        status_changed_by=owner,
        status_changed_by_name="Mike",
    )

    # Workspace is unshared initially:
    assert ws.is_shared is False
    assert s_list.is_shared is False
    assert item.is_shared is False
    assert item.status_actor_first_name == "Mike"
    # When unshared, changed_by_display must be empty:
    assert item.changed_by_display == ""

    res = client.get(reverse("shopping:list"))
    assert res.status_code == 200
    html = res.content.decode("utf-8")
    today_str = timezone.localtime(timezone.now()).strftime("%m/%d")
    # Date is shown, but neither username ("michael.klopot") nor first name ("Mike") appears in attribution
    assert today_str in html
    assert f"michael.klopot {today_str}" not in html
    assert f"Mike {today_str}" not in html
    assert 'title="Date placed or updated"' in html
    assert 'title="Date placed or updated by' not in html

    # Now share the workspace with collaborator:
    WorkspaceMember.objects.create(workspace=ws, user=collaborator, role=WorkspaceRole.EDITOR)
    ws.refresh_from_db()
    s_list.refresh_from_db()
    item.refresh_from_db()

    assert ws.is_shared is True
    assert s_list.is_shared is True
    assert item.is_shared is True
    # When shared, changed_by_display shows the first name "Mike", not username "michael.klopot"
    assert item.changed_by_display == "Mike"

    res_shared = client.get(reverse("shopping:list"))
    assert res_shared.status_code == 200
    shared_html = res_shared.content.decode("utf-8")
    # First name appears in attribution, full username does not
    assert f"Mike {today_str}" in shared_html
    assert f"michael.klopot {today_str}" not in shared_html
    assert 'title="Date placed or updated by Mike"' in shared_html

