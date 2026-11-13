"""
Unit and integration tests for Meal Plan Dish Suggestions,
course completeness heuristics, nutritional balance scoring,
and user-defined dietary rules (e.g. 'each dinner should have a vegetarian protein').
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import MealPlanRule
from apps.mealplans.services.mealplan_service import add_meal_to_plan, add_recipe_to_meal
from apps.mealplans.services.suggestion_service import (
    calculate_current_meal_nutrition,
    get_dish_suggestions,
    get_recipe_role,
)
from apps.recipes.models import Ingredient, Recipe

User = get_user_model()


@pytest.fixture
def suggestions_setup(db):
    """Fixture with users, workspace, and a diverse catalog of test recipes."""
    owner = User.objects.create_user(username="chef_lead", password="password")
    viewer = User.objects.create_user(username="viewer_user", password="password")

    ws = create_workspace("Suggestions Kitchen", owner)
    share_workspace(ws, viewer, WorkspaceRole.VIEWER)

    meal_plan = ws.get_meal_plan()
    shopping_list = ws.get_primary_list()

    # 1. Main Dish (Meat): Steak with Garlic Butter
    steak = Recipe.objects.create(
        name="Grilled Ribeye Steak",
        dish_type="Main Dish",
        meal_type=["dinner"],
        calories_per_serving=650,
        protein_per_serving_g=Decimal("45.0"),
        fiber_per_serving_g=Decimal("0.5"),
        dietary_restrictions=[],
    )
    Ingredient.objects.create(recipe=steak, name="Ribeye Steak", amount=Decimal("1.0"), amount_unit="lb", category="meat")

    # 2. Main Dish (Vegetarian Protein): Crispy Tofu Veggie Stir Fry
    tofu_stirfry = Recipe.objects.create(
        name="Crispy Tofu Veggie Stir Fry",
        dish_type="Main Dish",
        meal_type=["dinner", "lunch"],
        calories_per_serving=380,
        protein_per_serving_g=Decimal("24.0"),
        fiber_per_serving_g=Decimal("6.0"),
        dietary_restrictions=["Vegetarian", "Vegan"],
    )
    Ingredient.objects.create(recipe=tofu_stirfry, name="Extra Firm Tofu", amount=Decimal("14.0"), amount_unit="oz", category="produce")
    Ingredient.objects.create(recipe=tofu_stirfry, name="Broccoli Florets", amount=Decimal("2.0"), amount_unit="cups", category="produce")

    # 3. Main Dish (Tacos theme): Fiesta Street Tacos
    tacos = Recipe.objects.create(
        name="Fiesta Street Tacos",
        dish_type="Main Dish",
        meal_type=["dinner"],
        cuisine="Mexican",
        calories_per_serving=420,
        protein_per_serving_g=Decimal("26.0"),
        fiber_per_serving_g=Decimal("4.0"),
    )
    Ingredient.objects.create(recipe=tacos, name="Corn Tortillas", amount=Decimal("6.0"), amount_unit="count", category="bakery")
    Ingredient.objects.create(recipe=tacos, name="Flank Steak", amount=Decimal("0.75"), amount_unit="lb", category="meat")

    # 4. Salad: Mediterranean Crisp Salad
    salad = Recipe.objects.create(
        name="Mediterranean Crisp Salad",
        dish_type="Salad",
        meal_type=["lunch", "dinner"],
        calories_per_serving=180,
        protein_per_serving_g=Decimal("4.0"),
        fiber_per_serving_g=Decimal("5.0"),
        dietary_restrictions=["Vegetarian"],
    )
    Ingredient.objects.create(recipe=salad, name="Romaine Lettuce", amount=Decimal("1.0"), amount_unit="head", category="produce")
    Ingredient.objects.create(recipe=salad, name="Cucumbers", amount=Decimal("2.0"), amount_unit="count", category="produce")

    # 5. Soup: Roasted Tomato Basil Soup
    soup = Recipe.objects.create(
        name="Roasted Tomato Basil Soup",
        dish_type="Soup",
        meal_type=["lunch", "dinner"],
        calories_per_serving=190,
        protein_per_serving_g=Decimal("3.0"),
        fiber_per_serving_g=Decimal("3.5"),
        dietary_restrictions=["Vegetarian"],
    )
    Ingredient.objects.create(recipe=soup, name="Roma Tomatoes", amount=Decimal("2.0"), amount_unit="lb", category="produce")

    # 6. Dessert: Decadent Chocolate Lava Cake
    dessert = Recipe.objects.create(
        name="Decadent Chocolate Lava Cake",
        dish_type="Dessert",
        meal_type=["dessert"],
        calories_per_serving=480,
        protein_per_serving_g=Decimal("5.0"),
        fiber_per_serving_g=Decimal("2.0"),
        dietary_restrictions=["Vegetarian"],
    )
    Ingredient.objects.create(recipe=dessert, name="Dark Chocolate", amount=Decimal("200.0"), amount_unit="g", category="baking")

    # 7. Side: Garlic Mashed Potatoes
    side = Recipe.objects.create(
        name="Garlic Mashed Potatoes",
        dish_type="Side Dish",
        meal_type=["dinner"],
        calories_per_serving=220,
        protein_per_serving_g=Decimal("4.0"),
        fiber_per_serving_g=Decimal("3.0"),
        dietary_restrictions=["Vegetarian"],
    )
    Ingredient.objects.create(recipe=side, name="Russet Potatoes", amount=Decimal("2.0"), amount_unit="lb", category="produce")

    return {
        "owner": owner,
        "viewer": viewer,
        "workspace": ws,
        "meal_plan": meal_plan,
        "shopping_list": shopping_list,
        "steak": steak,
        "tofu_stirfry": tofu_stirfry,
        "tacos": tacos,
        "salad": salad,
        "soup": soup,
        "dessert": dessert,
        "side": side,
    }


def test_recipe_role_detection(suggestions_setup):
    """Verify get_recipe_role accurately tags culinary roles."""
    s = suggestions_setup
    assert get_recipe_role(s["steak"]) == "main"
    assert get_recipe_role(s["tofu_stirfry"]) == "main"
    assert get_recipe_role(s["tacos"]) == "main"
    assert get_recipe_role(s["salad"]) == "salad"
    assert get_recipe_role(s["soup"]) == "soup"
    assert get_recipe_role(s["dessert"]) == "dessert"
    assert get_recipe_role(s["side"]) == "side"


def test_calculate_current_meal_nutrition(suggestions_setup):
    """Verify nutrition aggregation across dishes planned in a meal."""
    meal_plan = suggestions_setup["meal_plan"]
    shopping_list = suggestions_setup["shopping_list"]
    salad = suggestions_setup["salad"]
    dessert = suggestions_setup["dessert"]

    meal = add_meal_to_plan(meal_plan, "Sunday Supper")
    add_recipe_to_meal(meal, salad, shopping_list)
    add_recipe_to_meal(meal, dessert, shopping_list)

    nutrition = calculate_current_meal_nutrition(meal)
    assert nutrition["calories"] == salad.calories_per_serving + dessert.calories_per_serving
    assert nutrition["protein"] == salad.protein_per_serving_g + dessert.protein_per_serving_g
    assert nutrition["fiber"] == salad.fiber_per_serving_g + dessert.fiber_per_serving_g


def test_course_completeness_missing_main_dish(suggestions_setup):
    """
    When a meal currently has only salad, soup, or dessert,
    the suggestion engine must strongly prioritize suggesting a main dish.
    """
    meal_plan = suggestions_setup["meal_plan"]
    shopping_list = suggestions_setup["shopping_list"]
    salad = suggestions_setup["salad"]
    dessert = suggestions_setup["dessert"]

    meal = add_meal_to_plan(meal_plan, "Dinner with Soup & Dessert")
    add_recipe_to_meal(meal, salad, shopping_list)
    add_recipe_to_meal(meal, dessert, shopping_list)

    suggestions = get_dish_suggestions(meal, limit=3)
    assert len(suggestions) > 0

    top_suggestion = suggestions[0]
    # The top suggestion must be a main dish
    assert top_suggestion.role == "main"
    assert any("main" in r.lower() or "hearty" in r.lower() for r in top_suggestion.reasons)


def test_course_completeness_main_already_present(suggestions_setup):
    """
    When a meal already has a main dish, the suggestion engine should prioritize
    complementary sides, salads, soups, or desserts rather than a second main.
    """
    meal_plan = suggestions_setup["meal_plan"]
    shopping_list = suggestions_setup["shopping_list"]
    steak = suggestions_setup["steak"]

    meal = add_meal_to_plan(meal_plan, "Steak Dinner")
    add_recipe_to_meal(meal, steak, shopping_list)

    suggestions = get_dish_suggestions(meal, limit=4)
    suggested_roles = [s.role for s in suggestions]

    # Complements (salad, side, soup, dessert) should outrank another main dish
    assert any(role in ("salad", "side", "soup", "dessert") for role in suggested_roles[:2])


def test_meal_name_theme_and_history(suggestions_setup):
    """
    Verify meal name matching (e.g. 'Taco Tuesday' matches taco dishes) and
    historical frequency boost when a dish previously appeared in identical meal names.
    """
    meal_plan = suggestions_setup["meal_plan"]
    shopping_list = suggestions_setup["shopping_list"]
    tacos = suggestions_setup["tacos"]

    # First, simulate history: a past meal 'Taco Fiesta' already had tacos
    old_meal = add_meal_to_plan(meal_plan, "Taco Fiesta")
    add_recipe_to_meal(old_meal, tacos, shopping_list)

    # Now create a new planned meal with the same name
    new_meal = add_meal_to_plan(meal_plan, "Taco Fiesta")
    suggestions = get_dish_suggestions(new_meal, limit=3)

    assert suggestions[0].recipe.id == tacos.id
    reasons_str = " ".join(suggestions[0].reasons)
    assert "Taco" in reasons_str or "Often enjoyed" in reasons_str


def test_nutritional_completeness_protein_gap(suggestions_setup):
    """
    When a meal has low protein (<15g), recipes with rich protein are boosted
    with a badge explaining the protein gap fulfillment.
    """
    meal_plan = suggestions_setup["meal_plan"]
    shopping_list = suggestions_setup["shopping_list"]
    salad = suggestions_setup["salad"]

    meal = add_meal_to_plan(meal_plan, "Light Lunch")
    add_recipe_to_meal(meal, salad, shopping_list)

    suggestions = get_dish_suggestions(meal, limit=3)
    protein_reasons = [r for s in suggestions for r in s.reasons if "protein" in r.lower()]
    assert len(protein_reasons) > 0


def test_user_defined_rule_vegetarian_protein(suggestions_setup):
    """
    Test user-defined rule: 'each dinner should have a vegetarian protein'.
    When active:
    - Vegetarian protein dishes (e.g. Crispy Tofu Veggie Stir Fry) get a major score boost
      and prominent badge '🥬 Fulfills rule: ...'.
    - Meat dishes receive a penalty.
    """
    meal_plan = suggestions_setup["meal_plan"]
    tofu_stirfry = suggestions_setup["tofu_stirfry"]
    steak = suggestions_setup["steak"]

    meal = add_meal_to_plan(meal_plan, "Monday Dinner")

    # Add the rule to the meal plan
    rule = MealPlanRule.objects.create(
        meal_plan=meal_plan,
        rule_text="each dinner should have a vegetarian protein",
        is_active=True,
    )

    suggestions = get_dish_suggestions(meal, limit=5)
    # The top suggestion must be the vegetarian protein stir fry
    assert suggestions[0].recipe.id == tofu_stirfry.id
    assert len(suggestions[0].rule_matches) > 0
    assert any("vegetarian protein" in m.lower() for m in suggestions[0].rule_matches)

    # Verify steak is ranked lower due to vegetarian rule penalty
    steak_indices = [idx for idx, s in enumerate(suggestions) if s.recipe.id == steak.id]
    if steak_indices:
        assert steak_indices[0] > 0

    # Test toggling the rule off
    rule.is_active = False
    rule.save()

    suggestions_without_rule = get_dish_suggestions(meal, limit=5)
    # Without the rule, steak is no longer penalized
    assert not any(len(s.rule_matches) > 0 for s in suggestions_without_rule)


def test_meal_suggestions_htmx_endpoint(client, suggestions_setup):
    """Test GET endpoint /mealplans/meal/<id>/suggestions/."""
    owner = suggestions_setup["owner"]
    meal_plan = suggestions_setup["meal_plan"]
    meal = add_meal_to_plan(meal_plan, "Family Dinner")

    client.force_login(owner)
    url = reverse("mealplans:meal_suggestions", kwargs={"meal_id": meal.id})
    response = client.get(url)

    assert response.status_code == 200
    assert "Recommended Dishes for Family Dinner" in response.content.decode()
    assert "Current meal:" in response.content.decode()
    assert "Add" in response.content.decode()
    assert "scale_factor" in response.content.decode()


def test_add_toggle_delete_meal_rules(client, suggestions_setup):
    """Test full CRUD endpoints for MealPlanRule."""
    owner = suggestions_setup["owner"]
    viewer = suggestions_setup["viewer"]
    meal_plan = suggestions_setup["meal_plan"]

    # 1. Viewer cannot add a rule
    client.force_login(viewer)
    add_url = reverse("mealplans:add_rule")
    resp_viewer = client.post(add_url, {"rule_text": "each dinner should have a vegetarian protein"})
    assert resp_viewer.status_code == 403

    # 2. Owner can add a rule
    client.force_login(owner)
    resp_owner = client.post(add_url, {"rule_text": "each dinner should have a vegetarian protein"})
    assert resp_owner.status_code == 200
    assert MealPlanRule.objects.filter(rule_text="each dinner should have a vegetarian protein").exists()

    rule = MealPlanRule.objects.get(rule_text="each dinner should have a vegetarian protein")
    assert rule.meal_plan == meal_plan
    assert rule.is_active is True

    # 3. Toggle rule
    toggle_url = reverse("mealplans:toggle_rule", kwargs={"rule_id": rule.id})
    resp_toggle = client.post(toggle_url)
    assert resp_toggle.status_code == 200
    rule.refresh_from_db()
    assert rule.is_active is False

    # 4. Delete rule
    delete_url = reverse("mealplans:delete_rule", kwargs={"rule_id": rule.id})
    resp_delete = client.post(delete_url)
    assert resp_delete.status_code == 200
    assert not MealPlanRule.objects.filter(id=rule.id).exists()
