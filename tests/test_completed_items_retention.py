"""
Unit and integration tests for per-workspace configurable completed items auto-removal.

Tests that items in 'Got' and 'Already Have' sections not associated with recipes
or preset lists are automatically purged according to the workspace's retention setting,
defaulting to one week (7 days), and configurable by workspace owners.
"""

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Workspace, WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import Meal, MealPlan
from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem
from apps.shopping.services.cleanup_service import (
    purge_all_expired_completed_items,
    purge_expired_completed_items,
)

User = get_user_model()


@pytest.fixture
def retention_setup(db):
    """Setup workspace with owner, primary list, and sample recipes/presets."""
    owner = User.objects.create_user(username="owner_user", first_name="Owner", password="pw")
    editor = User.objects.create_user(username="editor_user", first_name="Editor", password="pw")
    viewer = User.objects.create_user(username="viewer_user", first_name="Viewer", password="pw")

    workspace = create_workspace(name="Household List", owner=owner)
    share_workspace(workspace, editor, WorkspaceRole.EDITOR)
    share_workspace(workspace, viewer, WorkspaceRole.VIEWER)

    primary_list = workspace.get_primary_list()

    # Create recipe and ingredient
    recipe = Recipe.objects.create(name="Garlic Pasta", directions="Boil pasta.")
    ingredient = Ingredient.objects.create(recipe=recipe, name="garlic", amount=Decimal("2.00"), amount_unit="cloves")

    # Create meal plan and meal
    meal_plan = workspace.get_meal_plan()
    meal = Meal.objects.create(meal_plan=meal_plan, name="Dinner Tonight")

    # Create preset list
    preset = ShoppingList.objects.create(
        name="Weekly Dairy",
        workspace=workspace,
        is_preset=True,
    )

    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "workspace": workspace,
        "primary_list": primary_list,
        "recipe": recipe,
        "ingredient": ingredient,
        "meal": meal,
        "preset": preset,
    }


@pytest.mark.django_db
def test_workspace_default_retention_days(retention_setup):
    """Verify that a newly created workspace defaults to 7 days (1 week) retention."""
    ws = retention_setup["workspace"]
    assert ws.completed_items_retention_days == 7


@pytest.mark.django_db
def test_purge_expired_standalone_completed_items(retention_setup):
    """Verify standalone items in GOT or HAVE older than retention threshold are purged."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    # 1. Standalone item in GOT, 8 days old (older than 7 days) -> should be purged
    item_old_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Paper Towels",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=item_old_got.id).update(
        status_changed_at=now - datetime.timedelta(days=8)
    )

    # 2. Standalone item in HAVE, 10 days old -> should be purged
    item_old_have = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Sponges",
        amount=Decimal("2.00"),
        status=ItemStatus.HAVE,
    )
    ShoppingListItem.objects.filter(id=item_old_have.id).update(
        status_changed_at=now - datetime.timedelta(days=10)
    )

    # 3. Standalone item in GOT, 3 days old (within 7 days) -> should NOT be purged
    item_fresh_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Fresh Bread",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=item_fresh_got.id).update(
        status_changed_at=now - datetime.timedelta(days=3)
    )

    # 4. Standalone item in NEED, 20 days old -> should NEVER be purged
    item_old_need = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="New Lightbulb",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
    )
    ShoppingListItem.objects.filter(id=item_old_need.id).update(
        status_changed_at=now - datetime.timedelta(days=20)
    )

    purged = purge_expired_completed_items(ws)
    assert purged == 2

    remaining_ids = set(ShoppingListItem.objects.filter(shopping_list=s_list).values_list("id", flat=True))
    assert item_old_got.id not in remaining_ids
    assert item_old_have.id not in remaining_ids
    assert item_fresh_got.id in remaining_ids
    assert item_old_need.id in remaining_ids


@pytest.mark.django_db
def test_purge_preserves_recipe_and_preset_items(retention_setup):
    """Verify items linked to recipes or preset lists are NEVER purged even if older than retention."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    ingredient = retention_setup["ingredient"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]
    now = timezone.now()

    # Item with source_recipe in GOT 14 days ago
    item_recipe = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Rigatoni Pasta",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
        source_recipe=recipe,
    )
    ShoppingListItem.objects.filter(id=item_recipe.id).update(
        status_changed_at=now - datetime.timedelta(days=14)
    )

    # Item with source_ingredient in HAVE 14 days ago
    item_ingr = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Garlic",
        amount=Decimal("2.00"),
        status=ItemStatus.HAVE,
        source_ingredient=ingredient,
    )
    ShoppingListItem.objects.filter(id=item_ingr.id).update(
        status_changed_at=now - datetime.timedelta(days=14)
    )

    # Item with source_meal in GOT 14 days ago
    item_meal = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Parmesan Cheese",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
        source_meal=meal,
    )
    ShoppingListItem.objects.filter(id=item_meal.id).update(
        status_changed_at=now - datetime.timedelta(days=14)
    )

    # Item with source_preset in GOT 14 days ago
    item_preset = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Whole Milk",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
        source_preset=preset,
    )
    ShoppingListItem.objects.filter(id=item_preset.id).update(
        status_changed_at=now - datetime.timedelta(days=14)
    )

    purged = purge_expired_completed_items(ws)
    assert purged == 0

    remaining_ids = set(ShoppingListItem.objects.filter(shopping_list=s_list).values_list("id", flat=True))
    assert item_recipe.id in remaining_ids
    assert item_ingr.id in remaining_ids
    assert item_meal.id in remaining_ids
    assert item_preset.id in remaining_ids


@pytest.mark.django_db
def test_retention_disabled_when_zero_or_none(retention_setup):
    """Verify setting retention to 0 or None disables auto-removal."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    old_item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Batteries",
        amount=Decimal("4.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=old_item.id).update(
        status_changed_at=now - datetime.timedelta(days=30)
    )

    # Retention set to 0 (Never)
    ws.completed_items_retention_days = 0
    ws.save()
    assert purge_expired_completed_items(ws) == 0
    assert ShoppingListItem.objects.filter(id=old_item.id).exists()

    # Retention set to None
    ws.completed_items_retention_days = None
    ws.save()
    assert purge_expired_completed_items(ws) == 0
    assert ShoppingListItem.objects.filter(id=old_item.id).exists()


@pytest.mark.django_db
def test_custom_retention_duration(retention_setup):
    """Verify custom retention period (e.g. 3 days, 14 days)."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    item_4d = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Trash Bags",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=item_4d.id).update(
        status_changed_at=now - datetime.timedelta(days=4)
    )

    item_2d = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Dish Soap",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=item_2d.id).update(
        status_changed_at=now - datetime.timedelta(days=2)
    )

    # With 3 days retention: item_4d is purged, item_2d is kept
    ws.completed_items_retention_days = 3
    ws.save()

    purged = purge_expired_completed_items(ws)
    assert purged == 1
    assert not ShoppingListItem.objects.filter(id=item_4d.id).exists()
    assert ShoppingListItem.objects.filter(id=item_2d.id).exists()


@pytest.mark.django_db
def test_workspace_settings_modal_get(client, retention_setup):
    """Test retrieving workspace settings modal renders correctly with active tab and choices."""
    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]

    client.force_login(owner)
    url = reverse("core:workspace_settings", args=[ws.id])
    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Manage Workspace" in content
    assert "Auto-Remove Completed Items" in content
    assert "1 week (7 days) - Default" in content
    assert 'name="completed_items_retention_days"' in content


@pytest.mark.django_db
def test_update_workspace_settings_post(client, retention_setup):
    """Test updating workspace settings via POST."""
    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]
    viewer = retention_setup["viewer"]

    # Non-owner cannot update settings
    client.force_login(viewer)
    update_url = reverse("core:update_workspace_settings", args=[ws.id])
    forbidden_resp = client.post(
        update_url,
        {"name": "Hacked Name", "completed_items_retention_days": "1"},
    )
    assert forbidden_resp.status_code == 403

    # Owner can update settings
    client.force_login(owner)
    resp = client.post(
        update_url,
        {"name": "Renamed Workspace", "completed_items_retention_days": "14"},
    )
    assert resp.status_code == 200
    ws.refresh_from_db()
    assert ws.name == "Renamed Workspace"
    assert ws.completed_items_retention_days == 14


@pytest.mark.django_db
def test_update_workspace_settings_triggers_immediate_cleanup(client, retention_setup):
    """Test that saving a shorter retention duration immediately cleans up qualifying items."""
    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    # Create item in GOT 2 days ago
    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Napkins",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=item.id).update(
        status_changed_at=now - datetime.timedelta(days=2)
    )

    # Under 7 days (default), item stays
    client.force_login(owner)
    update_url = reverse("core:update_workspace_settings", args=[ws.id])

    # Change retention to 1 day
    resp = client.post(
        update_url,
        {"name": ws.name, "completed_items_retention_days": "1"},
    )
    assert resp.status_code == 200
    assert not ShoppingListItem.objects.filter(id=item.id).exists()
    assert "Purged 1 expired item" in resp.content.decode("utf-8")


@pytest.mark.django_db
def test_shopping_list_view_auto_purges_expired_items(client, retention_setup):
    """Test that rendering the shopping list view automatically triggers cleanup of expired items."""
    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    old_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Old Lightbulb",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=old_got.id).update(
        status_changed_at=now - datetime.timedelta(days=9)
    )

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    response = client.get(reverse("shopping:list"))
    assert response.status_code == 200
    assert not ShoppingListItem.objects.filter(id=old_got.id).exists()
