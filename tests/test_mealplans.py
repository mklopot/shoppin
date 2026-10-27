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
from apps.mealplans.models import Meal, MealDish
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
    assert b"3 ingredients added to shopping list" in resp_dish.content

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


def test_mark_dish_made_and_rating_prompt(client, mealplan_setup):
    """
    Test marking an individual dish as made:
    - Removes dish from meal plan and synchronizes shopping list
    - Increments recipe times_made counter
    - Creates RecipeMadeLog entry
    - Prompts for rating, allowing submission or skipping
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Taco Night")
    add_recipe_to_meal(meal, recipe, shopping_list)

    assert recipe.times_made == 0
    assert meal.recipes.filter(id=recipe.id).exists()
    assert shopping_list.items.filter(name="Ground Beef").exists()

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # Mark dish as made
    url = reverse("mealplans:mark_dish_made", args=[meal.id, recipe.id])
    resp = client.post(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    # Verify dish removed from meal
    assert not meal.recipes.filter(id=recipe.id).exists()
    # Verify shopping list ingredients deducted/removed
    assert not shopping_list.items.filter(name="Ground Beef").exists()

    # Verify times_made incremented
    recipe.refresh_from_db()
    assert recipe.times_made == 1

    # Verify rating modal rendered with Skip and Save options
    assert "Dish Made: Fiesta Tacos" in html
    assert "Skip Rating" in html
    assert "Save Rating" in html
    assert 'name="stars_' in html

    # Submit rating from the prompt
    rate_url = reverse("mealplans:submit_made_ratings")
    resp_rate = client.post(
        rate_url,
        {
            "recipe_id": [recipe.id],
            f"stars_{recipe.id}": "5",
            f"thumbs_up_{recipe.id}": "true",
        },
        HTTP_HX_REQUEST="true",
    )
    assert resp_rate.status_code == 200
    rate_html = resp_rate.content.decode("utf-8")
    assert '<div id="modal-placeholder"></div>' in rate_html
    assert '<div id="toast-container" hx-swap-oob="beforeend">' in rate_html
    assert "⭐ Saved 5★ rating" in rate_html
    assert recipe.ratings.filter(user=owner, stars=5, thumbs_up=True).exists()


def test_mark_entire_meal_made_and_skip_rating(client, mealplan_setup):
    """
    Test marking an entire meal as made:
    - Increments times_made for all recipes in the meal
    - Removes all dishes and deletes the meal
    - Prompts for rating, and verify user can skip rating
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    recipe1 = mealplan_setup["recipe"]

    recipe2 = Recipe.objects.create(
        name="Mexican Rice",
        cuisine="Mexican",
        directions="Cook rice with tomatoes.",
    )
    Ingredient.objects.create(
        recipe=recipe2,
        name="Rice",
        amount=Decimal("1.00"),
        amount_unit="cup",
    )

    meal = add_meal_to_plan(meal_plan, "Sunday Supper")
    add_recipe_to_meal(meal, recipe1, shopping_list)
    add_recipe_to_meal(meal, recipe2, shopping_list)

    assert recipe1.times_made == 0
    assert recipe2.times_made == 0

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # Mark entire meal as made
    url = reverse("mealplans:mark_meal_made", args=[meal.id])
    resp = client.post(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    # Verify meal deleted from plan
    assert not Meal.objects.filter(id=meal.id).exists()

    # Verify both recipe counters incremented
    recipe1.refresh_from_db()
    recipe2.refresh_from_db()
    assert recipe1.times_made == 1
    assert recipe2.times_made == 1

    # Verify rating modal prompts for both recipes and allows Skip
    assert "Meal Made: Sunday Supper" in html
    assert "Fiesta Tacos" in html
    assert "Mexican Rice" in html
    assert "Skip Rating" in html
    assert "Save Ratings" in html

    # Skipping rating: user closes modal without submitting, verify no ratings created
    assert not recipe1.ratings.filter(user=owner).exists()
    assert not recipe2.ratings.filter(user=owner).exists()


def test_times_made_counter_visibility_in_recipe_views(client, mealplan_setup):
    """
    Verify times_made counter is visible when viewing recipes in detail,
    modals, and card lists.
    """
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    recipe = mealplan_setup["recipe"]
    recipe.times_made = 4
    recipe.save()

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Full recipe detail view
    resp_detail = client.get(reverse("recipes:detail", args=[recipe.id]))
    assert resp_detail.status_code == 200
    detail_html = resp_detail.content.decode("utf-8")
    assert "Times Made" in detail_html
    assert "4 times" in detail_html

    # 2. Recipe quick-view modal in recipes tab
    resp_modal = client.get(reverse("recipes:detail", args=[recipe.id]) + "?modal=1", HTTP_HX_REQUEST="true")
    assert resp_modal.status_code == 200
    modal_html = resp_modal.content.decode("utf-8")
    assert "Times Made" in modal_html
    assert "4" in modal_html

    # 3. Recipe modal in mealplans tab
    resp_mp_modal = client.get(reverse("mealplans:recipe_modal", args=[recipe.id]))
    assert resp_mp_modal.status_code == 200
    mp_modal_html = resp_mp_modal.content.decode("utf-8")
    assert "Made 4 times" in mp_modal_html

    # 4. Recipe card in list view
    resp_list = client.get(reverse("recipes:list"))
    assert resp_list.status_code == 200
    list_html = resp_list.content.decode("utf-8")
    assert "Made 4 times" in list_html
    assert "View Recipe &rarr;" in list_html

    # Verify singular "Made 1 time" when times_made == 1
    recipe.times_made = 1
    recipe.save()
    resp_singular = client.get(reverse("recipes:list"))
    assert resp_singular.status_code == 200
    assert "Made 1 time" in resp_singular.content.decode("utf-8")


def test_add_dish_scaled_up_and_remove(mealplan_setup):
    """Verify adding a recipe scaled up (2x) doubles shopping list amounts and cleans up completely."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Sunday Party")
    add_recipe_to_meal(meal, recipe, shopping_list, scale_factor=Decimal("2.00"))

    # Verify MealDish record
    dish = MealDish.objects.get(meal=meal, recipe=recipe)
    assert dish.scale_factor == Decimal("2.00")
    assert dish.scale_display == "2x"
    assert dish.scaled_portions == 8  # 4 * 2

    # Verify shopping list items scaled by factor 2
    tortillas = shopping_list.items.get(name="Tortillas")
    assert tortillas.amount == Decimal("16.00")  # 8 * 2

    beef = shopping_list.items.get(name="Ground Beef")
    assert beef.amount == Decimal("2.00")  # 1 * 2

    # Verify remove deducts the full 2x scaled amounts
    remove_recipe_from_meal(meal, recipe, shopping_list)
    assert shopping_list.items.count() == 0
    assert not MealDish.objects.filter(meal=meal, recipe=recipe).exists()


def test_add_dish_scaled_down(mealplan_setup):
    """Verify adding a recipe scaled down (0.5x) halves shopping list amounts."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Solo Dinner")
    add_recipe_to_meal(meal, recipe, shopping_list, scale_factor=Decimal("0.50"))

    dish = MealDish.objects.get(meal=meal, recipe=recipe)
    assert dish.scale_factor == Decimal("0.50")
    assert dish.scale_display == "0.5x"
    assert dish.scaled_portions == 2  # 4 * 0.5

    tortillas = shopping_list.items.get(name="Tortillas")
    assert tortillas.amount == Decimal("4.00")  # 8 * 0.5

    beef = shopping_list.items.get(name="Ground Beef")
    assert beef.amount == Decimal("0.50")  # 1 * 0.5


def test_add_dish_scaled_combines_with_existing(mealplan_setup):
    """Verify adding a scaled recipe correctly combines amounts with existing items."""
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    # Pre-existing 3 Tortillas on shopping list
    shopping_list.items.create(
        name="Tortillas",
        amount=Decimal("3.00"),
        amount_unit="count",
        status=ItemStatus.NEED,
        category="bakery",
    )

    meal = add_meal_to_plan(meal_plan, "Big Taco Night")
    # Base: 8 Tortillas scaled by 1.5 = 12
    add_recipe_to_meal(meal, recipe, shopping_list, scale_factor=Decimal("1.50"))

    tortillas = shopping_list.items.get(name="Tortillas")
    # 3 pre-existing + 12 scaled = 15
    assert tortillas.amount == Decimal("15.00")


def test_add_dish_post_endpoint_with_scale_factor(client, mealplan_setup):
    """Verify adding a dish via POST /mealplans/meal/<id>/add-dish/ with scale_factor."""
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Family Feast")

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.post(
        reverse("mealplans:add_dish", args=[meal.id]),
        {"recipe": recipe.name, "scale_factor": "2.5"},
    )
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "2.5x" in html

    dish = MealDish.objects.get(meal=meal, recipe=recipe)
    assert dish.scale_factor == Decimal("2.50")
    assert dish.scaled_portions == 10  # 4 * 2.5

    tortillas = shopping_list.items.get(name="Tortillas")
    assert tortillas.amount == Decimal("20.00")  # 8 * 2.5


def test_recipe_add_to_mealplan_endpoint_with_scale_factor(client, mealplan_setup):
    """Verify adding a recipe via POST /recipes/<id>/add-to-mealplan/ with scale_factor."""
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Meal Prep")

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp = client.post(
        reverse("recipes:add_to_mealplan", args=[recipe.id]),
        {"meal_id": meal.id, "scale_factor": "0.5"},
    )
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "(0.5x)" in html

    tortillas = shopping_list.items.get(name="Tortillas")
    assert tortillas.amount == Decimal("4.00")


