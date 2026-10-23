"""
Unit and integration tests for Preset Lists and Recurring Schedules.
"""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem
from apps.shopping.services.preset_service import (
    add_preset_item,
    apply_preset_scheduled_refresh,
    check_and_apply_due_preset_schedules,
    create_preset_list,
    delete_preset_item,
    load_preset_items_to_shopping_list,
    update_preset_schedule,
)

User = get_user_model()


@pytest.fixture
def preset_setup(db):
    """Fixture providing workspace, owner, editor, viewer, and primary list."""
    owner = User.objects.create_user(username="preset_owner", password="password")
    editor = User.objects.create_user(username="preset_editor", password="password")
    viewer = User.objects.create_user(username="preset_viewer", password="password")

    ws = create_workspace("Test Preset Household", owner)
    share_workspace(ws, editor, WorkspaceRole.EDITOR)
    share_workspace(ws, viewer, WorkspaceRole.VIEWER)

    primary_list = ws.get_primary_list()

    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "workspace": ws,
        "primary_list": primary_list,
    }


@pytest.mark.django_db
def test_create_preset_list_and_items(preset_setup):
    """Test creating a preset list template and managing items."""
    ws = preset_setup["workspace"]

    preset = create_preset_list(
        workspace=ws,
        name="Weekly Essentials",
        interval_days=7,
        is_schedule_enabled=False,
    )
    assert preset.is_preset is True
    assert preset.name == "Weekly Essentials"
    assert preset.interval_days == 7
    assert preset.is_schedule_enabled is False

    # Add items with legacy attributes
    item1 = add_preset_item(
        preset_list=preset,
        name="Whole Milk",
        amount=Decimal("1.00"),
        amount_unit="gallon",
        brand="Horizon",
        vendor="King Soopers",
        category="dairy",
        optional=False,
    )
    item2 = add_preset_item(
        preset_list=preset,
        name="Eggs",
        amount="12",
        amount_unit="count",
        optional=True,
    )

    assert preset.items.count() == 2
    assert item1.brand == "Horizon"
    assert item1.vendor == "King Soopers"
    assert item1.category == "dairy"
    assert item2.optional is True
    assert item2.amount == Decimal("12.00")

    # Delete item
    deleted = delete_preset_item(preset, item2.id)
    assert deleted is True
    assert preset.items.count() == 1


@pytest.mark.django_db
def test_load_preset_items_to_shopping_list(preset_setup):
    """Test manually loading items from preset list to shopping list."""
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Spices")
    add_preset_item(preset, "Cumin", amount="1", amount_unit="jar")
    add_preset_item(preset, "Paprika", amount="1", amount_unit="jar")

    # Load items
    loaded = load_preset_items_to_shopping_list(preset, primary_list)
    assert len(loaded) == 2

    # Check that loaded items have source_preset set and status NEED and locked=True (confirmed)
    for it in primary_list.items.all():
        assert it.source_preset == preset
        assert it.status == ItemStatus.NEED
        assert it.locked is True
        assert f"Preset: {preset.name}" in it.purpose


@pytest.mark.django_db
def test_schedule_configuration_defaults_and_override(preset_setup):
    """Test user-configured interval defaulting to 1 week and allowing next_occurrence override."""
    ws = preset_setup["workspace"]

    preset = create_preset_list(ws, "Breakfast Supplies")
    assert preset.interval_days == 7
    assert preset.is_schedule_enabled is False

    # Enable schedule with custom interval and next_occurrence override
    future_time = timezone.now() + timedelta(days=3, hours=5)
    updated = update_preset_schedule(
        preset_list=preset,
        is_schedule_enabled=True,
        interval_days=14,
        next_occurrence=future_time,
    )

    assert updated.is_schedule_enabled is True
    assert updated.interval_days == 14
    assert updated.next_occurrence == future_time


@pytest.mark.django_db
def test_scheduled_refresh_removes_old_items_regardless_of_status_and_readds(preset_setup):
    """
    Test scheduled refresh execution:
    All entries previously added to the shopping list from the given preset list are removed,
    REGARDLESS of their status (NEED, GOT, HAVE, DONT_NEED), and then right away all of the active
    list items are added again fresh.
    """
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Weekly Staples", interval_days=7, is_schedule_enabled=True)
    add_preset_item(preset, "Milk", amount="1", amount_unit="gallon")
    add_preset_item(preset, "Bread", amount="1", amount_unit="loaf")
    add_preset_item(preset, "Eggs", amount="12", amount_unit="count")

    # Initial load to shopping list
    load_preset_items_to_shopping_list(preset, primary_list)
    assert primary_list.items.filter(source_preset=preset).count() == 3

    # Add an independent shopping item NOT from this preset
    independent_item = ShoppingListItem.objects.create(
        shopping_list=primary_list,
        name="Birthday Cake",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
    )

    # Change the statuses of the preset items on the shopping list
    # One to GOT, one to HAVE, one left at NEED
    items = list(primary_list.items.filter(source_preset=preset))
    items[0].status = ItemStatus.GOT
    items[0].save()
    items[1].status = ItemStatus.HAVE
    items[1].save()
    items[2].status = ItemStatus.DONT_NEED
    items[2].save()

    # Now execute scheduled refresh
    start_time = timezone.now()
    result = apply_preset_scheduled_refresh(preset, target_list=primary_list)

    assert result["removed_count"] == 3
    assert result["added_count"] == 3

    # Verify that independent item was NOT touched
    assert ShoppingListItem.objects.filter(id=independent_item.id).exists()

    # Verify all current items from preset on shopping list are active NEED status
    preset_shopping_items = primary_list.items.filter(source_preset=preset)
    assert preset_shopping_items.count() == 3
    for it in preset_shopping_items:
        assert it.status == ItemStatus.NEED
        assert it.locked is True

    # Verify preset schedule timestamps were advanced
    preset.refresh_from_db()
    assert preset.last_applied_at is not None
    assert preset.last_applied_at >= start_time
    assert preset.next_occurrence == preset.last_applied_at + timedelta(days=7)


@pytest.mark.django_db
def test_automatic_due_schedule_check(preset_setup):
    """Test check_and_apply_due_preset_schedules runs when next_occurrence <= now."""
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Auto Preset", interval_days=7, is_schedule_enabled=True)
    add_preset_item(preset, "Apples", amount="5")

    # Set next_occurrence in the past
    preset.next_occurrence = timezone.now() - timedelta(minutes=5)
    preset.save()

    assert preset.is_due_for_refresh() is True

    # Run due check
    results = check_and_apply_due_preset_schedules(ws)
    assert len(results) == 1
    assert results[0]["added_count"] == 1

    # Check that item is on primary shopping list
    assert primary_list.items.filter(source_preset=preset, name="Apples").exists()

    # Preset should no longer be due
    preset.refresh_from_db()
    assert preset.is_due_for_refresh() is False
    assert preset.next_occurrence > timezone.now()


@pytest.mark.django_db
def test_background_scheduler_process_due_schedules(preset_setup):
    """Test scheduler.process_due_schedules executes due presets across workspaces."""
    from apps.shopping.services.scheduler import process_due_schedules

    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Background Scheduled Preset", interval_days=7, is_schedule_enabled=True)
    add_preset_item(preset, "Greek Yogurt", amount="2", is_active=True)

    # Set due in the past
    preset.next_occurrence = timezone.now() - timedelta(minutes=10)
    preset.save()

    results = process_due_schedules()
    assert len(results) == 1
    assert results[0]["added_count"] == 1
    assert results[0]["removed_count"] == 0

    # Verify item was added to the primary shopping list
    assert primary_list.items.filter(name="Greek Yogurt", source_preset=preset).exists()

    # Verify preset schedule advanced to the future
    preset.refresh_from_db()
    assert preset.next_occurrence > timezone.now()
    assert preset.last_applied_at is not None


@pytest.mark.django_db
def test_management_command_run_preset_schedules(preset_setup):
    """Test management command 'run_preset_schedules' executes due preset lists."""
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Cron Preset", interval_days=7, is_schedule_enabled=True)
    add_preset_item(preset, "Coffee", amount="1", amount_unit="bag")

    # Set due in the past
    preset.next_occurrence = timezone.now() - timedelta(hours=1)
    preset.save()

    out = io.StringIO()
    call_command("run_preset_schedules", stdout=out)
    output = out.getvalue()

    assert "Found 1 preset list(s) to refresh" in output
    assert "Refreshed 'Cron Preset'" in output

    preset.refresh_from_db()
    assert primary_list.items.filter(source_preset=preset, name="Coffee").exists()


@pytest.mark.django_db
def test_preset_views_and_permissions(client, preset_setup):
    """Test preset list views and role-based permissions."""
    owner = preset_setup["owner"]
    viewer = preset_setup["viewer"]
    ws = preset_setup["workspace"]

    # 1. Owner views index
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.get("/preset-lists/")
    assert resp.status_code == 200
    assert b"Preset Lists" in resp.content

    # 2. Owner creates preset list with custom date and 12-hour AM/PM time
    resp = client.post("/preset-lists/create/", {
        "name": "Taco Night",
        "interval_days": "7",
        "is_schedule_enabled": "on",
        "next_occurrence_date": "2026-11-05",
        "next_occurrence_time": "2:30 PM",
    })
    assert resp.status_code == 302
    preset = ShoppingList.objects.get(name="Taco Night", is_preset=True)
    assert preset.is_schedule_enabled is True
    assert preset.interval_days == 7
    assert preset.next_occurrence is not None
    local_occurrence = timezone.localtime(preset.next_occurrence)
    assert local_occurrence.year == 2026
    assert local_occurrence.month == 11
    assert local_occurrence.day == 5
    assert local_occurrence.hour == 14
    assert local_occurrence.minute == 30

    # 3. Owner adds item
    resp = client.post(f"/preset-lists/{preset.id}/items/add/", {
        "name": "Tortillas",
        "amount": "10",
        "category": "bakery",
    })
    assert resp.status_code == 302
    assert preset.items.filter(name="Tortillas").exists()

    # 4. Immediate execution action ('Run Schedule Now')
    resp = client.post(f"/preset-lists/{preset.id}/run-schedule-now/")
    assert resp.status_code == 302
    primary_list = ws.get_primary_list()
    assert primary_list.items.filter(source_preset=preset, name="Tortillas").exists()

    # 5. Viewer has read-only access (write attempts rejected)
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # GET is allowed
    resp = client.get(f"/preset-lists/{preset.id}/")
    assert resp.status_code == 200

    # Write action is forbidden
    resp = client.post(f"/preset-lists/{preset.id}/items/add/", {
        "name": "Forbidden Item",
    })
    assert resp.status_code == 403


@pytest.mark.django_db
def test_preset_shopping_list_indicator_and_unload(client, preset_setup):
    """Test shopping list displays preset indicator with loaded status and schedule, and supports unload."""
    owner = preset_setup["owner"]
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    preset = create_preset_list(ws, "Breakfast Essentials", interval_days=7, is_schedule_enabled=True)
    add_preset_item(preset, "Oatmeal", amount="1", amount_unit="box")

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Initially not loaded
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Breakfast Essentials" in resp.content
    assert b"Every 7d" in resp.content

    # 2. Schedule modal endpoint
    resp = client.get(f"/preset-lists/{preset.id}/schedule-modal/")
    assert resp.status_code == 200
    assert b"Recurring Refresh Schedule" in resp.content

    # 3. Load items from preset onto shopping list
    resp = client.post(f"/preset-lists/{preset.id}/load/", {
        "from_shopping_list": "1",
    }, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert primary_list.items.filter(source_preset=preset, name="Oatmeal").exists()
    oatmeal_item = primary_list.items.get(source_preset=preset, name="Oatmeal")
    assert oatmeal_item.locked is True  # NOT "not confirmed"

    # Shopping list view now shows Loaded indicator
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Loaded (1)" in resp.content

    # 4. Unload preset from shopping list
    resp = client.post(f"/preset-lists/{preset.id}/unload/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert not primary_list.items.filter(source_preset=preset).exists()


@pytest.mark.django_db
def test_preset_item_active_inactive_slider_and_scheduling(client, preset_setup):
    """
    Test active/inactive slider for preset schedule items:
    - Inactive items remain on the preset list.
    - Inactive items show up on the individual items modal.
    - Inactive items do NOT load automatically via schedule refresh.
    - Inactive items can still be manually loaded if explicitly selected in the modal.
    """
    owner = preset_setup["owner"]
    ws = preset_setup["workspace"]
    primary_list = preset_setup["primary_list"]

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    preset = create_preset_list(ws, "Weekly Staples", interval_days=7, is_schedule_enabled=True)
    item_milk = add_preset_item(preset, "Whole Milk", amount="1", amount_unit="gal", is_active=True)
    item_eggs = add_preset_item(preset, "Dozen Eggs", amount="1", is_active=True)
    item_cinnamon = add_preset_item(preset, "Cinnamon", amount="1", is_active=False)

    # 1. Verify all 3 items remain on preset list
    assert preset.items.count() == 3
    assert item_milk.is_active is True
    assert item_cinnamon.is_active is False

    # 2. Toggle 'Eggs' to inactive via toggle endpoint
    resp = client.post(f"/preset-lists/{preset.id}/items/{item_eggs.id}/toggle-active/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    item_eggs.refresh_from_db()
    assert item_eggs.is_active is False

    # Preset items count is still 3 (inactive items remain on the list)
    assert preset.items.count() == 3
    assert b"Paused for schedule" in resp.content

    # 3. Automated schedule refresh should ONLY load active items (Milk)
    result = apply_preset_scheduled_refresh(preset, target_list=primary_list)
    assert result["added_count"] == 1
    assert primary_list.items.filter(source_preset=preset, name="Whole Milk").exists()
    assert not primary_list.items.filter(source_preset=preset, name="Dozen Eggs").exists()
    assert not primary_list.items.filter(source_preset=preset, name="Cinnamon").exists()

    # 4. Individual items modal displays ALL items, including inactive ones
    modal_resp = client.get(f"/preset-lists/{preset.id}/load-modal/")
    assert modal_resp.status_code == 200
    assert b"Whole Milk" in modal_resp.content
    assert b"Dozen Eggs" in modal_resp.content
    assert b"Cinnamon" in modal_resp.content
    assert b"Inactive on schedule" in modal_resp.content

    # 5. Toggle 'Eggs' back to active
    resp = client.post(f"/preset-lists/{preset.id}/items/{item_eggs.id}/toggle-active/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    item_eggs.refresh_from_db()
    assert item_eggs.is_active is True

    # 6. Next schedule refresh now loads both Milk and Eggs (but still not Cinnamon)
    result2 = apply_preset_scheduled_refresh(preset, target_list=primary_list)
    assert result2["added_count"] == 2
    assert primary_list.items.filter(source_preset=preset, name="Whole Milk").exists()
    assert primary_list.items.filter(source_preset=preset, name="Dozen Eggs").exists()
    assert not primary_list.items.filter(source_preset=preset, name="Cinnamon").exists()

    # 7. Inactive items can still be loaded if selected in manual modal
    resp = client.post(f"/preset-lists/{preset.id}/load/", {
        "item_ids": [str(item_cinnamon.id)],
        "replace_existing": "false",
    })
    assert resp.status_code in (200, 302)
    assert primary_list.items.filter(source_preset=preset, name="Cinnamon").exists()
