"""
Unit and integration tests for Meal Plans, recipe dish integration,
ingredient loading, readiness calculation, and emojification.
"""

import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import Meal, MealDish
from apps.mealplans.services.emojifier import get_meal_emoji
from apps.mealplans.services.mealplan_service import (
    add_item_to_meal,
    add_meal_to_plan,
    add_recipe_to_meal,
    compute_cooking_status,
    delete_meal_from_plan,
    remove_dish_from_meal,
    remove_recipe_from_meal,
    scale_meal_dish,
    update_meal_name,
)
from apps.recipes.models import Ingredient, Recipe, RecipeMadeLog
from apps.recipes.services.recipe_service import record_recipe_made
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

    # 4. Mark a required ingredient as DONT_NEED (Skipped) -> should now be Yellow (Missing optional or skipped)
    tortillas.status = ItemStatus.DONT_NEED
    tortillas.save(update_fields=["status"])

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id not in status["recipes_ready"]
    assert recipe.id in status["recipes_missing_optional"]
    assert meal.id not in status["meals_ready"]
    assert meal.id in status["meals_missing_optional"]

    # 5. Mark optional Cilantro as DONT_NEED (Skipped) while required are GOT/HAVE -> Yellow
    tortillas.status = ItemStatus.GOT
    tortillas.save(update_fields=["status"])
    cilantro.status = ItemStatus.DONT_NEED
    cilantro.save(update_fields=["status"])

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id not in status["recipes_ready"]
    assert recipe.id in status["recipes_missing_optional"]

    # 6. Mark required ingredient back to NEED while another is skipped -> Grey
    beef.status = ItemStatus.NEED
    beef.save(update_fields=["status"])

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id not in status["recipes_ready"]
    assert recipe.id not in status["recipes_missing_optional"]


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
    """Verify recipe detail modal endpoint renders recipe info, ingredients, and shopping statuses."""
    ws = mealplan_setup["workspace"]
    editor = mealplan_setup["editor"]
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]
    meal = add_meal_to_plan(meal_plan, "Fiesta Dinner")
    add_recipe_to_meal(meal, recipe, shopping_list)

    # Set distinct statuses for ingredients
    # Tortillas -> GOT
    tortillas = shopping_list.items.get(name="Tortillas")
    tortillas.status = ItemStatus.GOT
    tortillas.save(update_fields=["status"])

    # Ground Beef -> HAVE
    beef = shopping_list.items.get(name="Ground Beef")
    beef.status = ItemStatus.HAVE
    beef.save(update_fields=["status"])

    # Cilantro -> DONT_NEED (Skipped)
    cilantro = shopping_list.items.get(name="Cilantro")
    cilantro.status = ItemStatus.DONT_NEED
    cilantro.save(update_fields=["status"])

    # Add extra ingredient to recipe not on list to verify Missing status
    Ingredient.objects.create(
        recipe=recipe,
        name="Lime Wedges",
        amount=Decimal("2.00"),
        amount_unit="count",
        optional=True,
    )

    resp = client.get(f"{reverse('mealplans:recipe_modal', args=[recipe.id])}?meal_id={meal.id}")
    assert resp.status_code == 200
    assert b"Fiesta Tacos" in resp.content
    assert b"Warm tortillas" in resp.content
    assert b"Tortillas" in resp.content
    # Status badges
    assert b"Got" in resp.content
    assert b"Have" in resp.content
    assert b"Skipped" in resp.content
    assert b"Missing" in resp.content
    assert b"Lime Wedges" in resp.content


def test_recipe_updated_after_added_to_meal_plan_warning(client, mealplan_setup):
    """Verify discrete warning when a recipe was updated after being added to a meal plan."""
    from datetime import timedelta

    from django.utils import timezone

    ws = mealplan_setup["workspace"]
    editor = mealplan_setup["editor"]
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]
    meal = add_meal_to_plan(meal_plan, "Taco Night")
    add_recipe_to_meal(meal, recipe, shopping_list)

    dish = meal.dishes.get(recipe=recipe)

    # 1. Initially, dish was just created, recipe was not updated after
    assert not dish.is_recipe_updated_since_added

    resp = client.get(reverse("mealplans:detail"))
    assert resp.status_code == 200
    assert b"Recipe was updated on" not in resp.content

    resp_modal = client.get(f"{reverse('mealplans:recipe_modal', args=[recipe.id])}?meal_id={meal.id}&dish_id={dish.id}")
    assert resp_modal.status_code == 200
    assert b"This recipe was updated in your catalog after it was added to this meal plan" not in resp_modal.content

    # 2. Simulate updating the recipe after it was added to the meal plan
    Recipe.objects.filter(id=recipe.id).update(updated_at=timezone.now() + timedelta(hours=1))
    recipe.refresh_from_db()
    dish.refresh_from_db()

    assert dish.is_recipe_updated_since_added

    # Check meal plan view has the discrete warning badge
    resp = client.get(reverse("mealplans:detail"))
    assert resp.status_code == 200
    assert b"Updated" in resp.content
    assert b"Recipe was updated on" in resp.content

    # Check recipe modal has the discrete warning note
    resp_modal = client.get(f"{reverse('mealplans:recipe_modal', args=[recipe.id])}?meal_id={meal.id}&dish_id={dish.id}")
    assert resp_modal.status_code == 200
    assert b"Recipe updated" in resp_modal.content
    assert b"This recipe was updated in your catalog after it was added to this meal plan" in resp_modal.content


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

    # Verify dish stays visible in meal with made attribution
    dish = MealDish.objects.get(meal=meal, recipe=recipe)
    assert dish.is_made is True
    assert dish.made_by == owner
    assert dish.made_at is not None
    assert f"Made by {owner.username}" in html
    assert "Dish marked as made, shopping list updated" in html
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




def test_update_meal_name_service(mealplan_setup):
    """Test updating meal name directly via service function."""
    meal_plan = mealplan_setup["meal_plan"]
    meal = add_meal_to_plan(meal_plan, "Regular Dinner")
    assert meal.name == "Regular Dinner"

    updated = update_meal_name(meal, "Taco Tuesday Fiesta")
    assert updated.name == "Taco Tuesday Fiesta"
    assert "🌮" in updated.emoji
    meal.refresh_from_db()
    assert meal.name == "Taco Tuesday Fiesta"
    assert "🌮" in meal.emoji


def test_edit_meal_name_endpoints(client, mealplan_setup):
    """Verify GET and POST endpoints for editing meal name."""
    owner = mealplan_setup["owner"]
    viewer = mealplan_setup["viewer"]
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]

    meal = add_meal_to_plan(meal_plan, "Sunday Supper")

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. GET edit form
    resp_get = client.get(reverse("mealplans:edit_meal", args=[meal.id]))
    assert resp_get.status_code == 200
    assert 'name="name"' in resp_get.content.decode("utf-8")
    assert 'value="Sunday Supper"' in resp_get.content.decode("utf-8")

    # 2. GET cancel returns header
    resp_cancel = client.get(reverse("mealplans:edit_meal", args=[meal.id]) + "?cancel=1")
    assert resp_cancel.status_code == 200
    assert "Sunday Supper" in resp_cancel.content.decode("utf-8")
    assert 'name="name"' not in resp_cancel.content.decode("utf-8")

    # 3. POST new name updates meal and emoji
    resp_post = client.post(
        reverse("mealplans:edit_meal", args=[meal.id]),
        {"name": "Pizza Party Friday"},
    )
    assert resp_post.status_code == 200
    html = resp_post.content.decode("utf-8")
    assert "Pizza Party Friday" in html
    assert "🍕" in html
    assert "✏️" in html
    assert "✎" not in html
    meal.refresh_from_db()
    assert meal.name == "Pizza Party Friday"
    assert "🍕" in meal.emoji

    # 4. Viewer receives 403 Forbidden
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    resp_v_post = client.post(
        reverse("mealplans:edit_meal", args=[meal.id]),
        {"name": "Hacked Meal Name"},
    )
    assert resp_v_post.status_code == 403
    meal.refresh_from_db()
    assert meal.name == "Pizza Party Friday"


def test_view_endpoints_add_dish_twice_scale_and_delete_separately(client, mealplan_setup):
    """Verify adding dish twice via HTTP creates two separate entries, allows separate scaling and deletion."""
    user = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]
    meal = add_meal_to_plan(meal_plan, "Tuesday Tacos")
    recipe = mealplan_setup["recipe"]
    sl = mealplan_setup["shopping_list"]

    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Add recipe first time (scale 1)
    resp1 = client.post(
        reverse("mealplans:add_dish", args=[meal.id]),
        {"recipe_id": recipe.id, "scale_factor": "1"},
    )
    assert resp1.status_code == 200

    # 2. Add recipe second time (scale 2)
    resp2 = client.post(
        reverse("mealplans:add_dish", args=[meal.id]),
        {"recipe_id": recipe.id, "scale_factor": "2"},
    )
    assert resp2.status_code == 200

    # Verify both dishes show up in the HTML
    html = resp2.content.decode("utf-8")
    assert html.count(recipe.name) >= 2

    dishes = list(meal.dishes.all())
    assert len(dishes) == 2
    d1, d2 = dishes[0], dishes[1]
    assert d1.scale_factor == Decimal("1.00")
    assert d2.scale_factor == Decimal("2.00")

    # Shopping list has 1 + 2 = 3x tortillas (8 * 3 = 24)
    tortillas = sl.items.get(name__iexact="tortillas")
    assert tortillas.amount == Decimal("24.00")

    # 3. Scale dish 1 to 3x via POST scale_dish endpoint
    resp_scale = client.post(
        reverse("mealplans:scale_dish", args=[meal.id, d1.id]),
        {"scale_factor": "3"},
    )
    assert resp_scale.status_code == 200
    d1.refresh_from_db()
    assert d1.scale_factor == Decimal("3.00")
    # Tortillas now 3 + 2 = 5x (8 * 5 = 40)
    tortillas.refresh_from_db()
    assert tortillas.amount == Decimal("40.00")

    # 4. Delete dish 2 via POST delete_dish endpoint
    resp_del = client.post(
        reverse("mealplans:delete_dish", args=[meal.id, d2.id]),
    )
    assert resp_del.status_code == 200

    # Only dish 1 remains
    assert meal.dishes.count() == 1
    remaining_dish = meal.dishes.first()
    assert remaining_dish.id == d1.id
    # Tortillas now 3x (8 * 3 = 24)
    tortillas.refresh_from_db()
    assert tortillas.amount == Decimal("24.00")


def test_add_single_item_to_meal_service_and_remove(mealplan_setup):
    """
    Verify adding a single ingredient/item in place of a dish sets the meal name as
    purpose on the shopping list, supports scaling and meal renaming, and removes
    the item from the shopping list when deleted.
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]

    meal = add_meal_to_plan(meal_plan, "Wednesday Quick Dinner")
    dish1, item1 = add_item_to_meal(
        meal=meal,
        raw_item_input="Rotisserie Chicken",
        shopping_list=shopping_list,
        amount_override="1",
    )
    dish2, item2 = add_item_to_meal(
        meal=meal,
        raw_item_input="Bagged Salad",
        shopping_list=shopping_list,
        amount_override="2 bags",
    )

    assert dish1.is_single_item is True
    assert dish1.recipe is None
    assert dish1.display_name == "Rotisserie Chicken"
    assert dish1.quantity_display == "1"

    assert dish2.is_single_item is True
    assert dish2.display_name == "Bagged Salad"
    assert dish2.quantity_display == "2 bags"

    item1.refresh_from_db()
    item2.refresh_from_db()
    assert item1.purpose == "Wednesday Quick Dinner"
    assert item1.source_meal == meal
    assert item1.amount == Decimal("1.00")

    assert item2.purpose == "Wednesday Quick Dinner"
    assert item2.source_meal == meal
    assert item2.amount == Decimal("2.00")
    assert item2.amount_unit == "bags"

    # Renaming the meal updates the purpose on the shopping list items
    update_meal_name(meal, "Thursday Easy Dinner")
    item1.refresh_from_db()
    item2.refresh_from_db()
    assert item1.purpose == "Thursday Easy Dinner"
    assert item2.purpose == "Thursday Easy Dinner"

    # Scaling a single-item dish updates the shopping list amount
    scale_meal_dish(dish2, Decimal("1.50"), shopping_list)
    item2.refresh_from_db()
    assert item2.amount == Decimal("3.00")

    # Removing dish1 removes Rotisserie Chicken from the shopping list
    remove_dish_from_meal(dish1, shopping_list)
    assert not shopping_list.items.filter(name__iexact="Rotisserie Chicken").exists()
    assert shopping_list.items.filter(name__iexact="Bagged Salad").exists()

    # Deleting the meal removes the remaining single item from the shopping list
    delete_meal_from_plan(meal, shopping_list)
    assert not shopping_list.items.filter(name__iexact="Bagged Salad").exists()


def test_single_item_combines_with_recipe_ingredient_and_cleans_up(mealplan_setup):
    """
    Verify a single item on a meal combines with a matching recipe ingredient on the
    shopping list, includes the meal name in purpose, and deducts cleanly when removed.
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal1 = add_meal_to_plan(meal_plan, "Tuesday Tacos")
    add_recipe_to_meal(meal1, recipe, shopping_list)

    meal2 = add_meal_to_plan(meal_plan, "Friday Quesadillas")
    single_dish, combined_item = add_item_to_meal(
        meal=meal2,
        raw_item_input="Tortillas",
        shopping_list=shopping_list,
        amount_override="4 count",
    )

    combined_item.refresh_from_db()
    assert combined_item.amount == Decimal("12.00")  # 8 from Fiesta Tacos + 4 from Friday Quesadillas
    assert "Fiesta Tacos" in combined_item.purpose
    assert "Friday Quesadillas" in combined_item.purpose

    # Removing the single item leaves the recipe's 8 Tortillas intact
    remove_dish_from_meal(single_dish, shopping_list)
    combined_item.refresh_from_db()
    assert combined_item.amount == Decimal("8.00")
    assert combined_item.purpose == "Fiesta Tacos"


def test_single_item_cooking_readiness_status(mealplan_setup):
    """
    Verify compute_cooking_status tracks readiness for single-item dishes and incorporates
    them into the parent meal's readiness status.
    """
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Combo Meal")
    add_recipe_to_meal(meal, recipe, shopping_list)
    single_dish, single_item = add_item_to_meal(
        meal=meal,
        raw_item_input="Corn on the Cob",
        shopping_list=shopping_list,
        amount_override="4",
    )

    # Mark all recipe ingredients as GOT, leave single_item as NEED
    for item in shopping_list.items.exclude(id=single_item.id):
        item.status = ItemStatus.GOT
        item.save()

    status = compute_cooking_status(meal_plan, shopping_list)
    assert recipe.id in status["recipes_ready"]
    assert single_dish.id not in status["dishes_ready"]
    assert meal.id not in status["meals_ready"]

    # Mark single_item as DONT_NEED (skipped) -> yellow (missing_optional)
    single_item.status = ItemStatus.DONT_NEED
    single_item.save()
    status = compute_cooking_status(meal_plan, shopping_list)
    assert single_dish.id in status["dishes_missing_optional"]
    assert meal.id in status["meals_missing_optional"]

    # Mark single_item as GOT -> green (ready)
    single_item.status = ItemStatus.GOT
    single_item.save()
    status = compute_cooking_status(meal_plan, shopping_list)
    assert single_dish.id in status["dishes_ready"]
    assert meal.id in status["meals_ready"]


def test_single_item_dedicated_entry_view_and_exempt_from_ratings(client, mealplan_setup):
    """
    Verify the dedicated add_single_item endpoint, visual distinction in HTML,
    and exemption from ratings/feedback when marked as made individually or as part of a meal.
    """
    owner = mealplan_setup["owner"]
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Italian Night")

    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Add a single item via dedicated endpoint
    resp_add = client.post(
        reverse("mealplans:add_single_item", args=[meal.id]),
        {"item_name": "Garlic Bread", "amount": "2 loaves"},
    )
    assert resp_add.status_code == 200
    html = resp_add.content.decode("utf-8")
    assert "Single Item" in html
    assert "Garlic Bread" in html
    assert "Qty: 2 loaves" in html

    single_dish = MealDish.objects.get(meal=meal, item_name="Garlic Bread")
    assert single_dish.is_single_item is True

    sl_item = shopping_list.items.get(name="Garlic Bread")
    assert sl_item.purpose == "Italian Night"
    assert sl_item.amount == Decimal("2.00")
    assert sl_item.amount_unit == "loaves"

    # 2. Mark single item as made individually -> stays visible with made attribution, removes shopping item, NO rating modal
    resp_made_single = client.post(
        reverse("mealplans:mark_dish_made", args=[meal.id, single_dish.id]),
    )
    assert resp_made_single.status_code == 200
    made_html = resp_made_single.content.decode("utf-8")
    assert "recipe-rating-modal" not in made_html
    assert resp_made_single.context["recipes"] == []
    single_dish.refresh_from_db()
    assert single_dish.is_made is True
    assert single_dish.made_by == owner
    assert single_dish.made_at is not None
    assert f"Made by {owner.username}" in made_html
    assert not shopping_list.items.filter(name="Garlic Bread").exists()

    # 3. Meal with BOTH a recipe dish and a single item -> mark_meal_made only prompts rating for the recipe
    add_recipe_to_meal(meal, recipe, shopping_list)
    add_item_to_meal(meal, "Caesar Salad Kit", shopping_list, amount_override="1 bag")
    initial_times_made = recipe.times_made

    resp_meal_made = client.post(
        reverse("mealplans:mark_meal_made", args=[meal.id]),
    )
    assert resp_meal_made.status_code == 200
    meal_made_html = resp_meal_made.content.decode("utf-8")
    assert "recipe-rating-modal" in meal_made_html
    assert resp_meal_made.context["recipes"] == [recipe]
    assert "Fiesta Tacos" in meal_made_html
    assert "Caesar Salad Kit" not in meal_made_html
    recipe.refresh_from_db()
    assert recipe.times_made == initial_times_made + 1
    assert shopping_list.items.count() == 0

    # 4. Meal with ONLY a single item -> mark_meal_made removes meal & shopping item and shows NO rating modal
    solo_meal = add_meal_to_plan(meal_plan, "Bagel Breakfast")
    add_item_to_meal(solo_meal, "Everything Bagels", shopping_list, amount_override="6")
    assert shopping_list.items.filter(name="Everything Bagels", purpose="Bagel Breakfast").exists()

    resp_solo_made = client.post(
        reverse("mealplans:mark_meal_made", args=[solo_meal.id]),
    )
    assert resp_solo_made.status_code == 200
    solo_made_html = resp_solo_made.content.decode("utf-8")
    assert "recipe-rating-modal" not in solo_made_html
    assert resp_solo_made.context["recipes"] == []
    assert not Meal.objects.filter(id=solo_meal.id).exists()
    assert not shopping_list.items.filter(name="Everything Bagels").exists()


@pytest.mark.django_db
def test_made_counts_breakdown_total_workspace_and_user(client, mealplan_setup):
    """
    Verify recipe UI and cooking endpoints track and display total times made,
    times made by anyone in the current workspace, and times made by the current user.
    """
    owner = mealplan_setup["owner"]
    editor = mealplan_setup["editor"]
    ws1 = mealplan_setup["workspace"]
    meal_plan1 = mealplan_setup["meal_plan"]
    shopping_list1 = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    ws2 = create_workspace("Cabin Kitchen", owner)
    outsider = User.objects.create_user(username="outside_cook", password="password")
    ws_outsider = create_workspace("Outside Kitchen", outsider)

    # Mark dish made twice by owner in ws1 via endpoint (1x via mark_dish_made, 1x via mark_meal_made)
    meal1 = add_meal_to_plan(meal_plan1, "Tuesday Tacos")
    add_recipe_to_meal(meal1, recipe, shopping_list1)
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws1.id
    session.save()

    resp_dish = client.post(reverse("mealplans:mark_dish_made", args=[meal1.id, recipe.id]), HTTP_HX_REQUEST="true")
    assert resp_dish.status_code == 200
    dish_html = resp_dish.content.decode("utf-8")
    assert "Made 1 time total" in dish_html
    assert "Workspace: 1" in dish_html
    assert "You: 1" in dish_html

    meal2 = add_meal_to_plan(meal_plan1, "Friday Tacos")
    add_recipe_to_meal(meal2, recipe, shopping_list1)
    resp_meal = client.post(reverse("mealplans:mark_meal_made", args=[meal2.id]), HTTP_HX_REQUEST="true")
    assert resp_meal.status_code == 200
    meal_html = resp_meal.content.decode("utf-8")
    assert "Made 2 times total" in meal_html
    assert re.search(r"Workspace:\s*<strong[^>]*>2</strong>", meal_html)
    assert re.search(r"You:\s*<strong[^>]*>2</strong>", meal_html)

    # Editor (also a member of ws1) cooks the recipe once in ws1
    meal3 = add_meal_to_plan(meal_plan1, "Editor Tacos")
    add_recipe_to_meal(meal3, recipe, shopping_list1)
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws1.id
    session.save()
    resp_ed = client.post(reverse("mealplans:mark_dish_made", args=[meal3.id, recipe.id]), HTTP_HX_REQUEST="true")
    assert resp_ed.status_code == 200
    ed_html = resp_ed.content.decode("utf-8")
    assert "Made 3 times total" in ed_html
    assert "Workspace: 3" in ed_html
    assert "You: 1" in ed_html

    # Owner cooks the recipe once in ws2, outsider cooks 3 times in ws_outsider
    record_recipe_made(recipe, user=owner, workspace=ws2)
    for _ in range(3):
        record_recipe_made(recipe, user=outsider, workspace=ws_outsider)

    # Legacy log (workspace=None) by a ws1 member also counts in ws1 and for that user
    record_recipe_made(recipe, user=editor, workspace=None)

    recipe.refresh_from_db()
    assert recipe.times_made == 8
    assert RecipeMadeLog.objects.filter(recipe=recipe, workspace=ws1).count() == 3
    assert RecipeMadeLog.objects.filter(recipe=recipe, workspace=ws2).count() == 1

    # Check all recipe views as owner in ws1: Total=8, ws1=4 (owner 2 + editor 1 + legacy editor 1), owner=3
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws1.id
    session.save()

    detail_html = client.get(reverse("recipes:detail", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times Total" in detail_html
    assert "Workspace: 4" in detail_html
    assert "By You: 3" in detail_html
    assert "In Culinary Workspace:" in detail_html

    modal_html = client.get(
        reverse("recipes:detail", args=[recipe.id]) + "?modal=1", HTTP_HX_REQUEST="true"
    ).content.decode("utf-8")
    assert "Made 8 times total" in modal_html
    assert "Workspace:" in modal_html and ">4<" in modal_html
    assert "You:" in modal_html and ">3<" in modal_html

    list_html = client.get(reverse("recipes:list")).content.decode("utf-8")
    assert "Made 8 times total" in list_html
    assert "Workspace:" in list_html and ">4<" in list_html
    assert "You:" in list_html and ">3<" in list_html

    prompt_html = client.get(reverse("recipes:prompt_add_to_mealplan", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times total" in prompt_html
    assert "Workspace:" in prompt_html and ">4<" in prompt_html
    assert "You:" in prompt_html and ">3<" in prompt_html

    mp_modal_html = client.get(reverse("mealplans:recipe_modal", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times total" in mp_modal_html
    assert "Workspace:" in mp_modal_html and ">4<" in mp_modal_html
    assert "You:" in mp_modal_html and ">3<" in mp_modal_html

    # Switch owner to ws2 ("Cabin Kitchen"): Total=8, ws2=1 (owner in ws2 only), owner=3
    session = client.session
    session["active_workspace_id"] = ws2.id
    session.save()
    ws2_detail = client.get(reverse("recipes:detail", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times Total" in ws2_detail
    assert "Workspace: 1" in ws2_detail
    assert "By You: 3" in ws2_detail
    assert "In Cabin Kitchen:" in ws2_detail

    # Check editor in ws1: Total=8, ws1=4, editor=2 (1 in ws1 + 1 legacy)
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws1.id
    session.save()
    ed_detail = client.get(reverse("recipes:detail", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times Total" in ed_detail
    assert "Workspace: 4" in ed_detail
    assert "By You: 2" in ed_detail

    # Anonymous viewer sees only total count without Workspace / By You labels
    client.logout()
    anon_detail = client.get(reverse("recipes:detail", args=[recipe.id])).content.decode("utf-8")
    assert "Made 8 times" in anon_detail
    assert "Workspace:" not in anon_detail
    assert "By You:" not in anon_detail


@pytest.mark.django_db
def test_recipe_modal_shows_edit_link_according_to_permissions(client, mealplan_setup):
    """Meal plan dish modal shows Edit Recipe / Modify link to writers and hides it from viewers."""
    ws = mealplan_setup["workspace"]
    owner = mealplan_setup["owner"]
    editor = mealplan_setup["editor"]
    viewer = mealplan_setup["viewer"]
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    recipe = mealplan_setup["recipe"]

    meal = add_meal_to_plan(meal_plan, "Dinner")
    add_recipe_to_meal(meal, recipe, shopping_list)
    edit_url = reverse("recipes:edit", args=[recipe.id])
    modal_url = f"{reverse('mealplans:recipe_modal', args=[recipe.id])}?meal_id={meal.id}"

    # 1. Curated/unowned recipe (created_by=None) -> owner sees Edit Recipe link
    client.force_login(owner)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    owner_html = client.get(modal_url).content.decode("utf-8")
    assert f'href="{edit_url}"' in owner_html
    assert "Edit Recipe" in owner_html

    # 2. Recipe owned by owner -> editor sees Modify / Adapt link to recipes:edit
    recipe.created_by = owner
    recipe.save(update_fields=["created_by"])
    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    editor_html = client.get(modal_url).content.decode("utf-8")
    assert f'href="{edit_url}"' in editor_html
    assert "Modify / Adapt" in editor_html

    # 3. Read-only viewer -> edit link hidden
    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()
    viewer_html = client.get(modal_url).content.decode("utf-8")
    assert f'href="{edit_url}"' not in viewer_html


@pytest.mark.django_db
def test_mark_single_dish_made_keeps_dish_visible_with_attribution_and_readiness(client, mealplan_setup):
    """
    When an individual dish in a meal is marked as made:
    - The dish remains visible in the meal showing made status, timestamp, and actor
    - Its shopping list items are deducted while remaining unmade dishes still govern readiness
    - Scale and Made controls for the made dish are hidden and blocked from mutation/double-counting
    - Marking the whole meal made afterwards cleans up everything without double-counting made dishes
    """
    ws = mealplan_setup["workspace"]
    meal_plan = mealplan_setup["meal_plan"]
    shopping_list = mealplan_setup["shopping_list"]
    editor = mealplan_setup["editor"]
    editor.first_name = "Alex"
    editor.save(update_fields=["first_name"])
    recipe1 = mealplan_setup["recipe"]

    recipe2 = Recipe.objects.create(
        name="Simple Pasta",
        cuisine="Italian",
        directions="Boil pasta.",
    )
    Ingredient.objects.create(
        recipe=recipe2,
        name="Penne Pasta",
        amount=Decimal("1.00"),
        amount_unit="box",
    )

    meal = add_meal_to_plan(meal_plan, "Mixed Dinner")
    add_recipe_to_meal(meal, recipe1, shopping_list)
    add_recipe_to_meal(meal, recipe2, shopping_list)
    add_item_to_meal(meal, "Garlic Bread", shopping_list, amount_override="1 loaf")
    dish1 = MealDish.objects.get(meal=meal, recipe=recipe1)
    dish2 = MealDish.objects.get(meal=meal, recipe=recipe2)
    dish3 = MealDish.objects.get(meal=meal, item_name="Garlic Bread")

    # Mark recipe1 & Garlic Bread items as GOT, leave Penne Pasta as NEED
    for item_name in ("Ground Beef", "Tortillas", "Cilantro", "Garlic Bread"):
        item = shopping_list.items.get(name=item_name)
        item.status = ItemStatus.GOT
        item.save(update_fields=["status"])

    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Mark dish1 as made -> stays visible with Alex's attribution & timestamp
    resp = client.post(reverse("mealplans:mark_dish_made", args=[meal.id, dish1.id]), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    dish1.refresh_from_db()
    assert dish1.is_made is True
    assert dish1.made_by == editor
    assert dish1.made_by_name == "Alex"
    assert dish1.made_at is not None
    recipe1.refresh_from_db()
    assert recipe1.times_made == 1
    assert RecipeMadeLog.objects.filter(recipe=recipe1).count() == 1
    assert not shopping_list.items.filter(name="Ground Beef").exists()

    # Check rendered meal plan content directly
    plan_html = client.get(reverse("mealplans:detail")).content.decode("utf-8")
    assert re.search(
        r"Made by Alex\s*&bull;\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{1,2}:\d{2}\s+[AP]M",
        plan_html,
    )
    # Dish 1's mark_dish_made and scale_dish controls are hidden, while delete_dish remains; dish 2 still has them
    assert reverse("mealplans:mark_dish_made", args=[meal.id, dish1.id]) not in plan_html
    assert reverse("mealplans:scale_dish", args=[meal.id, dish1.id]) not in plan_html
    assert reverse("mealplans:delete_dish", args=[meal.id, dish1.id]) in plan_html
    assert reverse("mealplans:mark_dish_made", args=[meal.id, dish2.id]) in plan_html
    assert reverse("mealplans:scale_dish", args=[meal.id, dish2.id]) in plan_html
    assert reverse("mealplans:mark_dish_made", args=[meal.id, dish3.id]) in plan_html

    # Recipe modal for dish1 shows the made-by banner
    modal_html = client.get(
        f"{reverse('mealplans:recipe_modal', args=[recipe1.id])}?meal_id={meal.id}&dish_id={dish1.id}"
    ).content.decode("utf-8")
    assert "Marked as made" in modal_html
    assert "Alex" in modal_html

    # 2. Readiness: dish1 is in dishes_made; meal is not ready while dish2 still needs Penne Pasta
    status = compute_cooking_status(meal_plan, shopping_list)
    assert dish1.id in status["dishes_made"]
    assert meal.id not in status["meals_ready"]

    pasta = shopping_list.items.get(name="Penne Pasta")
    pasta.status = ItemStatus.GOT
    pasta.save(update_fields=["status"])
    status_ready = compute_cooking_status(meal_plan, shopping_list)
    assert dish1.id in status_ready["dishes_made"]
    assert meal.id in status_ready["meals_ready"]

    # 3. Re-posting mark_dish_made or scale_dish on dish1 does not double-count or mutate scale
    resp_repeat = client.post(reverse("mealplans:mark_dish_made", args=[meal.id, dish1.id]), HTTP_HX_REQUEST="true")
    assert resp_repeat.status_code == 200
    recipe1.refresh_from_db()
    assert recipe1.times_made == 1
    assert RecipeMadeLog.objects.filter(recipe=recipe1).count() == 1

    resp_scale = client.post(
        reverse("mealplans:scale_dish", args=[meal.id, dish1.id]),
        {"scale_factor": "3"},
        HTTP_HX_REQUEST="true",
    )
    assert resp_scale.status_code == 200
    dish1.refresh_from_db()
    assert dish1.scale_factor == Decimal("1.00")

    # 4. Marking the entire meal made cleans up the meal and increments recipe2 without double-counting recipe1
    resp_meal = client.post(reverse("mealplans:mark_meal_made", args=[meal.id]), HTTP_HX_REQUEST="true")
    assert resp_meal.status_code == 200
    assert resp_meal.context["recipes"] == [recipe2]
    recipe1.refresh_from_db()
    recipe2.refresh_from_db()
    assert recipe1.times_made == 1
    assert recipe2.times_made == 1
    assert RecipeMadeLog.objects.filter(recipe=recipe1).count() == 1
    assert RecipeMadeLog.objects.filter(recipe=recipe2).count() == 1
    assert not Meal.objects.filter(id=meal.id).exists()
    assert shopping_list.items.count() == 0
