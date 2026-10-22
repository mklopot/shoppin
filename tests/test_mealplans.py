"""
Unit and integration tests for Meal Plans, recipe dish integration,
ingredient loading, readiness calculation, and emojification.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import Meal
from apps.mealplans.services.emojifier import get_meal_emoji
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    compute_cooking_status,
    delete_meal_from_plan,
    remove_recipe_from_meal,
)
from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import ItemStatus

User = get_user_model()


@pytest.fixture
def mealplan_setup(db):
    """Fixture providing workspace, owner, editor, viewer, recipe, and shopping list."""
    owner = User.objects.create_user(username="chef_owner", password="password")
    editor = User.objects.create_user(username="chef_editor", password="password")
    viewer = User.objects.create_user(username="chef_viewer", password="password")

    ws = create_workspace("Culinary Workspace", owner)
    share_workspace(ws, editor, WorkspaceRole.EDITOR)
    share_workspace(ws, viewer, WorkspaceRole.VIEWER)

    shopping_list = ws.get_primary_list()
    meal_plan = ws.get_meal_plan()

    # Create a test recipe with required and optional ingredients
    recipe = Recipe.objects.create(
        name="Fiesta Tacos",
        description="Delicious Mexican street tacos",
        directions="1. Warm tortillas. 2. Brown meat. 3. Assemble and enjoy.",
        cuisine="Mexican",
    )
    Ingredient.objects.create(
        recipe=recipe,
        name="Tortillas",
        amount=Decimal("8.00"),
        amount_unit="count",
        category="bakery",
        optional=False,
    )
    Ingredient.objects.create(
        recipe=recipe,
        name="Ground Beef",
        amount=Decimal("1.00"),
        amount_unit="lb",
        category="meat",
        optional=False,
    )
    Ingredient.objects.create(
        recipe=recipe,
        name="Cilantro",
        amount=Decimal("1.00"),
        amount_unit="bunch",
        category="produce",
        optional=True,
    )

    return {
        "workspace": ws,
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "shopping_list": shopping_list,
        "meal_plan": meal_plan,
        "recipe": recipe,
    }


def test_meal_emojifier():
    """Verify that meal names are automatically emojified with keywords."""
    assert "🌮" in get_meal_emoji("Taco Tuesday")
    assert "🍕" in get_meal_emoji("Friday Night Pizza")
    assert "🍔" in get_meal_emoji("Veggie Burger BBQ")
    assert "🍲" in get_meal_emoji("Chicken Noodle Soup")
    assert "🥞" in get_meal_emoji("Sunday Morning Pancakes")
    assert get_meal_emoji("Random Dish Without Match") == ""


def test_add_meal_to_plan(mealplan_setup):
    """Test adding a meal and verifying auto-emojification."""
    meal_plan = mealplan_setup["meal_plan"]
    meal = add_meal_to_plan(meal_plan, "Taco Fiesta")

    assert meal.id is not None
    assert meal.name == "Taco Fiesta"
    assert "🌮" in meal.emoji
    assert meal.meal_plan == meal_plan
    assert meal_plan.meals.count() == 1


def test_add_dish_loads_ingredients_onto_shopping_list(mealplan_setup):
    """Verify that adding a recipe dish to a meal loads its ingredients onto the shopping list."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Tuesday Dinner")
    add_recipe_to_meal(meal, recipe, shopping_list)

    assert meal.recipes.filter(id=recipe.id).exists()

    # Verify shopping list items created
    items = shopping_list.items.all()
    assert items.count() == 3

    tortillas = items.get(name="Tortillas")
    assert tortillas.amount == Decimal("8.00")
    assert tortillas.status == ItemStatus.NEED
    assert tortillas.purpose == "Fiesta Tacos"
    assert not tortillas.purpose.startswith("For ")
    assert tortillas.purpose_display == "Fiesta Tacos"
    assert tortillas.source_recipe == recipe

    beef = items.get(name="Ground Beef")
    assert beef.amount == Decimal("1.00")
    assert beef.optional is False

    cilantro = items.get(name="Cilantro")
    assert cilantro.optional is True


def test_add_dish_combines_existing_ingredient(mealplan_setup):
    """Verify that adding a recipe combines amounts with existing matching NEED items."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    # Pre-existing item on shopping list: 4 Tortillas (previously confirmed)
    shopping_list.items.create(
        name="Tortillas",
        amount=Decimal("4.00"),
        amount_unit="count",
        status=ItemStatus.NEED,
        category="bakery",
        locked=True,
    )

    meal = add_meal_to_plan(meal_plan, "Taco Dinner")
    add_recipe_to_meal(meal, recipe, shopping_list)

    tortillas = shopping_list.items.get(name="Tortillas")
    # 4 existing + 8 from recipe = 12
    assert tortillas.amount == Decimal("12.00")
    # Because it was combined and amount changed, confirmation status is reset
    assert tortillas.locked is False


def test_remove_recipe_from_meal_cleans_up_shopping_list(mealplan_setup):
    """Verify that removing a recipe removes its ingredients from the shopping list."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Mexican Night")
    add_recipe_to_meal(meal, recipe, shopping_list)
    assert shopping_list.items.count() == 3

    # Remove recipe
    remove_recipe_from_meal(meal, recipe, shopping_list)
    assert meal.recipes.count() == 0
    assert shopping_list.items.count() == 0


def test_delete_meal_removes_all_dish_ingredients(mealplan_setup):
    """Verify that deleting a meal completely removes its ingredients."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Saturday Feast")
    add_recipe_to_meal(meal, recipe, shopping_list)
    assert shopping_list.items.count() == 3

    delete_meal_from_plan(meal, shopping_list)
    assert meal_plan.meals.count() == 0
    assert shopping_list.items.count() == 0


def test_cooking_readiness_status(mealplan_setup):
    """Verify cooking readiness calculation (🟢 Ready, 🟡 Missing optional, ⚪ Needed)."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Taco Night")
    add_recipe_to_meal(meal, recipe, shopping_list)

    # 1. Initially, all ingredients are in NEED -> neither ready nor missing optional
    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id not in status["recipes_ready"]
    assert recipe.id not in status["recipes_missing_optional"]
    assert meal.id not in status["meals_ready"]

    # 2. Put required ingredients in GOT, leaving only optional Cilantro in NEED
    tortillas = shopping_list.items.get(name="Tortillas")
    beef = shopping_list.items.get(name="Ground Beef")
    tortillas.status = ItemStatus.GOT
    tortillas.save(update_fields=["status"])
    beef.status = ItemStatus.HAVE
    beef.save(update_fields=["status"])

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id in status["recipes_missing_optional"]
    assert meal.id in status["meals_missing_optional"]
    assert recipe.id not in status["recipes_ready"]

    # 3. Put optional Cilantro in GOT as well -> now 100% Ready to Cook!
    cilantro = shopping_list.items.get(name="Cilantro")
    cilantro.status = ItemStatus.GOT
    cilantro.save(update_fields=["status"])

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id in status["recipes_ready"]
    assert meal.id in status["meals_ready"]


def test_mealplan_views_and_read_only_permissions(client, mealplan_setup):
    """Verify meal plan views and 403 Forbidden enforcement for read-only viewers."""
    ws = mealplan_setup["workspace"]
    viewer = mealplan_setup["viewer"]
    editor = mealplan_setup["editor"]
    recipe = mealplan_setup["recipe"]

    # 1. Editor can view and add meal
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.get(reverse("mealplans:detail"))
    assert resp.status_code == 200
    assert b"Meal Plan" in resp.content

    resp_add = client.post(reverse("mealplans:add_meal"), {"meal": "Sunday Brunch"})
    assert resp_add.status_code == 200
    meal = Meal.objects.get(name="Sunday Brunch")

    # Editor adds dish and receives toast notifications for dish and ingredients
    resp_dish = client.post(
        reverse("mealplans:add_dish", args=[meal.id]),
        {"recipe_id": recipe.id},
    )
    assert resp_dish.status_code == 200
    assert meal.recipes.filter(id=recipe.id).exists()
    assert b"Added &#x27;Fiesta Tacos&#x27; to Sunday Brunch" in resp_dish.content or b"Added 'Fiesta Tacos' to Sunday Brunch" in resp_dish.content
    assert b"Tortillas to shopping list" in resp_dish.content
    assert b"Ground Beef to shopping list" in resp_dish.content
    assert b"Cilantro to shopping list" in resp_dish.content

    # 2. Viewer receives 403 Forbidden on mutations
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # Viewer cannot add meal
    resp_v_add = client.post(reverse("mealplans:add_meal"), {"meal": "Unauthorized Meal"})
    assert resp_v_add.status_code == 403

    # Viewer cannot delete meal
    resp_v_del = client.post(reverse("mealplans:delete_meal", args=[meal.id]))
    assert resp_v_del.status_code == 403

    # Viewer cannot add dish
    resp_v_dish = client.post(reverse("mealplans:add_dish", args=[meal.id]), {"recipe_id": recipe.id})
    assert resp_v_dish.status_code == 403

    # Viewer cannot delete dish
    resp_v_del_dish = client.post(reverse("mealplans:delete_dish", args=[meal.id, recipe.id]))
    assert resp_v_del_dish.status_code == 403


def test_recipe_modal_view(client, mealplan_setup):
    """Verify recipe detail modal endpoint renders recipe info and ingredients."""
    recipe = mealplan_setup["recipe"]
    resp = client.get(reverse("mealplans:recipe_modal", args=[recipe.id]))
    assert resp.status_code == 200
    assert b"Fiesta Tacos" in resp.content
    assert b"Warm tortillas" in resp.content
    assert b"Tortillas" in resp.content


def test_dish_purpose_formatting_and_no_duplicate_for(client, mealplan_setup):
    """
    Verify that item purposes originating from recipes do not contain duplicate 'For '
    and render as 'For [dish name]' without 'For For '.
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    recipe1 = mealplan_setup["recipe"]  # "Fiesta Tacos"

    # Create a second recipe sharing "Tortillas"
    recipe2 = Recipe.objects.create(
        name="Enchilada Bake",
        directions="Bake enchiladas.",
    )
    Ingredient.objects.create(
        recipe=recipe2,
        name="Tortillas",
        amount=Decimal("4.00"),
        amount_unit="count",
        category="bakery",
    )

    meal = add_meal_to_plan(meal_plan, "Dinner Night")
    add_recipe_to_meal(meal, recipe1, shopping_list)

    tortillas = shopping_list.items.get(name="Tortillas")
    # Verify no leading "For " is stored
    assert tortillas.purpose == "Fiesta Tacos"
    assert not tortillas.purpose.startswith("For ")
    assert tortillas.purpose_display == "Fiesta Tacos"

    # Add second dish that combines tortillas
    add_recipe_to_meal(meal, recipe2, shopping_list)
    tortillas.refresh_from_db()
    assert tortillas.purpose == "Fiesta Tacos, Enchilada Bake"
    assert not tortillas.purpose.startswith("For ")
    assert tortillas.purpose_display == "Fiesta Tacos, Enchilada Bake"

    # Even if an item has leading "For " assigned, model save() cleans it automatically
    tortillas.purpose = "For For Fiesta Tacos, Enchilada Bake"
    tortillas.save()
    tortillas.refresh_from_db()
    assert tortillas.purpose == "Fiesta Tacos, Enchilada Bake"
    assert tortillas.purpose_display == "Fiesta Tacos, Enchilada Bake"

    # Render list view via client and verify no "For For" exists in HTML
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.get(reverse("shopping:list"))
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "For Fiesta Tacos, Enchilada Bake" in content
    assert "For For" not in content
