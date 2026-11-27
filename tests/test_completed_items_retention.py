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

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import Meal
from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, ShoppingListItemSource
from apps.shopping.services.cleanup_service import (
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
    """Verify items connected to recipes or preset lists are NEVER purged even if older than retention."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    ingredient = retention_setup["ingredient"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]
    now = timezone.now()

    # Item with source_recipe in GOT 14 days ago -> must NOT be purged
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

    # Item with source_ingredient in HAVE 14 days ago -> must NOT be purged
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

    # Item with source_meal in GOT 14 days ago -> must NOT be purged
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

    # Item with source_preset in GOT 14 days ago -> must NOT be purged
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

    # Standalone / quick-added item in GOT 14 days ago -> SHOULD be purged
    standalone_old_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Paper Cups",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItem.objects.filter(id=standalone_old_got.id).update(
        status_changed_at=now - datetime.timedelta(days=14)
    )

    purged = purge_expired_completed_items(ws)
    assert purged == 1

    remaining_ids = set(ShoppingListItem.objects.filter(shopping_list=s_list).values_list("id", flat=True))
    assert item_recipe.id in remaining_ids
    assert item_ingr.id in remaining_ids
    assert item_meal.id in remaining_ids
    assert item_preset.id in remaining_ids
    assert standalone_old_got.id not in remaining_ids


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


@pytest.mark.django_db
def test_purge_counts_only_items_not_cascaded_attributions(retention_setup):
    """Verify purged count reflects deleted ShoppingListItem count, not cascaded attribution rows."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    now = timezone.now()

    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Dishwasher Pods",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
    )
    ShoppingListItemSource.objects.create(
        item=item,
        is_one_time=True,
        amount=Decimal("1.00"),
        purpose="one-time purchase",
    )
    ShoppingListItem.objects.filter(id=item.id).update(
        status_changed_at=now - datetime.timedelta(days=8)
    )

    purged = purge_expired_completed_items(ws)
    assert purged == 1
    assert not ShoppingListItem.objects.filter(id=item.id).exists()


@pytest.mark.django_db
def test_purge_cleans_orphaned_items_with_stale_source_fks_and_only_onetime_attribution(retention_setup):
    """Items whose attributions are purely one-time must purge even if stale source_* fields remain."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]
    now = timezone.now()

    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Stale Combined Salt",
        amount=Decimal("1.00"),
        status=ItemStatus.GOT,
        source_recipe=recipe,
        source_meal=meal,
        source_preset=preset,
    )
    ShoppingListItemSource.objects.create(
        item=item,
        is_one_time=True,
        amount=Decimal("1.00"),
        purpose="one-time purchase",
    )
    ShoppingListItem.objects.filter(id=item.id).update(
        status_changed_at=now - datetime.timedelta(days=10)
    )

    purged = purge_expired_completed_items(ws)
    assert purged == 1
    assert not ShoppingListItem.objects.filter(id=item.id).exists()


@pytest.mark.django_db
def test_deleting_recipe_or_meal_or_preset_unlinks_items_for_purge(retention_setup):
    """Deleting a Recipe, Meal, or Preset recalculates combined items and removes uncombined ones cleanly."""
    from apps.mealplans.services.mealplan_service import add_recipe_to_meal
    from apps.shopping.services.preset_service import (
        add_preset_item,
        load_preset_items_to_shopping_list,
    )

    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]
    now = timezone.now()

    # 1. Standalone "garlic" combined with recipe "Garlic Pasta"
    standalone_garlic = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="garlic",
        amount=Decimal("1.00"),
        amount_unit="cloves",
        purpose="one-time purchase",
        status=ItemStatus.NEED,
    )
    ShoppingListItemSource.objects.create(
        item=standalone_garlic,
        is_one_time=True,
        amount=Decimal("1.00"),
        amount_unit="cloves",
        purpose="one-time purchase",
    )
    add_recipe_to_meal(meal, recipe, s_list)

    # Also test an item solely from a second recipe
    recipe_only = Recipe.objects.create(name="Toast", directions="Toast bread.")
    Ingredient.objects.create(recipe=recipe_only, name="Sourdough Bread", amount=Decimal("2.00"), amount_unit="slices")
    add_recipe_to_meal(meal, recipe_only, s_list)

    ShoppingListItem.objects.filter(shopping_list=s_list).update(
        status=ItemStatus.GOT,
        status_changed_at=now - datetime.timedelta(days=9),
    )

    # Delete both recipes directly -> recipe_only's item is removed, standalone_garlic is unlinked
    recipe.delete()
    recipe_only.delete()

    assert not ShoppingListItem.objects.filter(shopping_list=s_list, name="Sourdough Bread").exists()
    standalone_garlic.refresh_from_db()
    assert standalone_garlic.source_recipe is None
    assert standalone_garlic.source_meal is None
    assert standalone_garlic.source_ingredient is None
    assert standalone_garlic.amount == Decimal("1.00")

    # Now standalone_garlic is eligible for retention purge
    assert purge_expired_completed_items(ws) == 1
    assert not ShoppingListItem.objects.filter(id=standalone_garlic.id).exists()

    # 2. Standalone item combined with Preset, then Preset deleted directly
    add_preset_item(preset, "Butter", amount="1", amount_unit="lb")
    standalone_butter = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Butter",
        amount=Decimal("1.00"),
        amount_unit="lb",
        purpose="one-time purchase",
        status=ItemStatus.NEED,
    )
    ShoppingListItemSource.objects.create(
        item=standalone_butter,
        is_one_time=True,
        amount=Decimal("1.00"),
        amount_unit="lb",
        purpose="one-time purchase",
    )
    load_preset_items_to_shopping_list(preset, s_list)
    ShoppingListItem.objects.filter(id=standalone_butter.id).update(
        status=ItemStatus.GOT,
        status_changed_at=now - datetime.timedelta(days=9),
    )

    preset.delete()
    standalone_butter.refresh_from_db()
    assert standalone_butter.source_preset is None
    assert standalone_butter.amount == Decimal("1.00")
    assert purge_expired_completed_items(ws) == 1
    assert not ShoppingListItem.objects.filter(id=standalone_butter.id).exists()


@pytest.mark.django_db
def test_edit_item_combine_preserves_attributions_and_allows_subsequent_purge(client, retention_setup):
    """Combining items via edit_item preserves attributions so removing the recipe later lets the standalone item purge."""
    from apps.mealplans.services.mealplan_service import add_recipe_to_meal, remove_dish_from_meal

    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    meal = retention_setup["meal"]
    now = timezone.now()

    add_recipe_to_meal(meal, recipe, s_list)
    recipe_garlic = s_list.items.get(name="garlic")
    recipe_garlic.status = ItemStatus.GOT
    recipe_garlic.save(update_fields=["status"])

    standalone_extra = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="roasted garlic",
        amount=Decimal("1.00"),
        amount_unit="cloves",
        purpose="one-time purchase",
        status=ItemStatus.GOT,
    )
    ShoppingListItemSource.objects.create(
        item=standalone_extra,
        is_one_time=True,
        amount=Decimal("1.00"),
        amount_unit="cloves",
        purpose="one-time purchase",
    )

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # Rename standalone_extra to "garlic" so edit_item combines it into recipe_garlic
    res = client.post(
        reverse("shopping:edit_item", args=[standalone_extra.id]),
        {
            "name": "garlic",
            "amount": "1 cloves",
            "amount_unit": "cloves",
            "category": "produce",
            "brand": "",
            "vendor": "",
            "purpose": "one-time purchase",
        },
    )
    assert res.status_code == 200
    assert not ShoppingListItem.objects.filter(id=standalone_extra.id).exists()

    recipe_garlic.refresh_from_db()
    assert recipe_garlic.amount == Decimal("3.00")
    assert recipe_garlic.attributions.count() == 2

    # Remove dish from meal -> only standalone 1 clove remains, source_recipe/source_meal cleared
    dish = meal.dishes.first()
    remove_dish_from_meal(dish, s_list)
    recipe_garlic.refresh_from_db()
    assert recipe_garlic.amount == Decimal("1.00")
    assert recipe_garlic.source_recipe is None
    assert recipe_garlic.source_meal is None

    # Age past 7 days -> now properly purged!
    ShoppingListItem.objects.filter(id=recipe_garlic.id).update(
        status_changed_at=now - datetime.timedelta(days=8)
    )
    assert purge_expired_completed_items(ws) == 1
    assert not ShoppingListItem.objects.filter(id=recipe_garlic.id).exists()


@pytest.mark.django_db
def test_workspace_settings_modal_null_retention_shows_never_disabled(client, retention_setup):
    """When completed_items_retention_days is None, settings dropdown selects '0' (Never) matching cleanup behavior."""
    ws = retention_setup["workspace"]
    owner = retention_setup["owner"]
    ws.completed_items_retention_days = None
    ws.save(update_fields=["completed_items_retention_days"])

    client.force_login(owner)
    resp = client.get(reverse("core:workspace_settings", args=[ws.id]))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert '<option value="0" selected>' in html
    assert '<option value="7" selected>' not in html


@pytest.mark.django_db
def test_purge_cleans_legacy_onetime_purchase_with_stale_source_links(retention_setup):
    """
    Pre-attribution (e.g. 10/29) items converted to 'one-time purchase' retain stale source_*
    FKs; they must still be purged after retention while active/mixed recipe items remain.
    """
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    ingredient = retention_setup["ingredient"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]
    old_ts = timezone.now() - datetime.timedelta(days=25)

    legacy_recipe_remnant = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Eggs",
        amount=Decimal("1.00"),
        purpose="one-time purchase",
        status=ItemStatus.GOT,
        source_recipe=recipe,
        source_meal=meal,
        source_ingredient=ingredient,
    )
    legacy_preset_remnant = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Salt",
        amount=Decimal("1.00"),
        purpose="For one-time purchase",
        status=ItemStatus.HAVE,
        source_preset=preset,
    )
    mixed_item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Olive Oil",
        amount=Decimal("2.00"),
        purpose="one-time purchase, Creamy Pasta",
        status=ItemStatus.GOT,
        source_recipe=recipe,
    )
    active_recipe_item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Pasta",
        amount=Decimal("1.00"),
        purpose="Creamy Pasta",
        status=ItemStatus.GOT,
        source_recipe=recipe,
    )
    ShoppingListItem.objects.filter(
        id__in=[
            legacy_recipe_remnant.id,
            legacy_preset_remnant.id,
            mixed_item.id,
            active_recipe_item.id,
        ]
    ).update(status_changed_at=old_ts, updated_at=old_ts)

    purged = purge_expired_completed_items(ws)
    assert purged == 2

    remaining_ids = set(ShoppingListItem.objects.filter(shopping_list=s_list).values_list("id", flat=True))
    assert legacy_recipe_remnant.id not in remaining_ids
    assert legacy_preset_remnant.id not in remaining_ids
    assert mixed_item.id in remaining_ids
    assert active_recipe_item.id in remaining_ids


@pytest.mark.django_db
def test_edit_item_to_onetime_purchase_clears_legacy_source_and_allows_purge(client, retention_setup):
    """Editing an unattributed legacy recipe item to 'one-time purchase' clears stale source FKs cleanly."""
    ws = retention_setup["workspace"]
    s_list = retention_setup["primary_list"]
    owner = retention_setup["owner"]
    recipe = retention_setup["recipe"]
    meal = retention_setup["meal"]
    old_ts = timezone.now() - datetime.timedelta(days=25)

    legacy_item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Eggs",
        amount=Decimal("1.00"),
        purpose="Creamy Pasta",
        status=ItemStatus.GOT,
        source_recipe=recipe,
        source_meal=meal,
    )
    client.force_login(owner)
    resp = client.post(
        reverse("shopping:edit_item", args=[legacy_item.id]),
        {"name": "Eggs", "amount": "1", "purpose": ""},
    )
    assert resp.status_code == 200

    legacy_item.refresh_from_db()
    assert legacy_item.purpose == "one-time purchase"
    assert legacy_item.source_recipe is None
    assert legacy_item.source_meal is None

    # Merge another stale one-time item into an item via edit_item to verify _ensure_item_has_attribution
    stale_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Milk",
        amount=Decimal("1.00"),
        purpose="one-time purchase",
        status=ItemStatus.GOT,
        source_recipe=recipe,
        source_meal=meal,
    )
    extra_got = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Cream",
        amount=Decimal("1.00"),
        purpose="one-time purchase",
        status=ItemStatus.GOT,
    )
    ShoppingListItemSource.objects.create(
        item=extra_got,
        is_one_time=True,
        amount=Decimal("1.00"),
        purpose="one-time purchase",
    )
    resp_merge = client.post(
        reverse("shopping:edit_item", args=[extra_got.id]),
        {"name": "Milk", "amount": "1", "purpose": "one-time purchase"},
    )
    assert resp_merge.status_code == 200
    stale_got.refresh_from_db()
    assert not stale_got.attributions.filter(recipe__isnull=False).exists()
    assert not stale_got.attributions.filter(meal__isnull=False).exists()

    ShoppingListItem.objects.filter(id__in=[legacy_item.id, stale_got.id]).update(
        status_changed_at=old_ts, updated_at=old_ts
    )
    assert purge_expired_completed_items(ws) == 2


@pytest.mark.django_db
def test_migration_0018_clears_orphaned_onetime_sources(retention_setup):
    """Data migration 0018 clears stale source FKs on unattributed one-time items while preserving real links."""
    import importlib

    from django.apps import apps as django_apps

    s_list = retention_setup["primary_list"]
    recipe = retention_setup["recipe"]
    meal = retention_setup["meal"]
    preset = retention_setup["preset"]

    orphan = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Eggs",
        amount=Decimal("1.00"),
        purpose="one-time purchase",
        status=ItemStatus.GOT,
        source_recipe=recipe,
        source_meal=meal,
    )
    active_preset = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Spices",
        amount=Decimal("1.00"),
        purpose="Preset: Pantry",
        status=ItemStatus.GOT,
        source_preset=preset,
    )

    mig = importlib.import_module("apps.shopping.migrations.0018_cleanup_orphaned_onetime_sources")
    mig.clear_orphaned_onetime_sources(django_apps, None)

    orphan.refresh_from_db()
    active_preset.refresh_from_db()
    assert orphan.source_recipe is None
    assert orphan.source_meal is None
    assert active_preset.source_preset == preset


@pytest.mark.django_db
def test_purge_expired_completed_items_skips_write_transaction_when_none_expired(retention_setup):
    """When no items are expired, purge_expired_completed_items must perform a read-only check with zero DELETE queries."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    ws = retention_setup["workspace"]
    with CaptureQueriesContext(connection) as ctx:
        deleted = purge_expired_completed_items(ws, force=True)

    assert deleted == 0
    assert not any("DELETE" in q["sql"].upper() for q in ctx.captured_queries)
