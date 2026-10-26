"""
Tests for recipe nutritional analysis calculation and macro suggestions.
"""

from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.recipes.models import Ingredient, Recipe
from apps.recipes.services.nutrition_service import (
    calculate_recipe_nutrition,
    clean_food_name,
    convert_ingredient_to_grams,
    filter_recipes_by_nutrition,
    match_ingredient_to_food,
    suggest_recipes_by_macro_goal,
    update_recipe_nutrition,
)


def test_clean_food_name():
    """Verify stripping of preparation adjectives and parentheticals."""
    assert clean_food_name("fresh ripe avocados") == "avocados"
    assert clean_food_name("med onion ((1 cup), finely chopped)") == "onion"
    assert clean_food_name("boneless skinless chicken breasts") == "chicken breasts"
    assert clean_food_name("kosher salt") == "salt"
    assert clean_food_name("extra virgin olive oil") == "olive oil"


def test_match_ingredient_to_food():
    """Test matching ingredient strings to nutritional database items."""
    food, matched, label = match_ingredient_to_food("peanut butter")
    assert matched is True
    assert food["cals"] >= 500

    food_chicken, matched_c, _ = match_ingredient_to_food("diced chicken breast")
    assert matched_c is True
    assert food_chicken["protein"] >= 25.0

    # Fallback category matching
    food_cat, matched_cat, _ = match_ingredient_to_food("rare venison cut", category="meat")
    assert food_cat["protein"] >= 15.0


def test_convert_ingredient_to_grams():
    """Verify weight, volume, and count conversions to grams."""
    food_bread, _, _ = match_ingredient_to_food("bread")
    # 2 slices of bread ~ 60g
    g_bread = convert_ingredient_to_grams(2.0, "slices", food_bread)
    assert 50.0 <= g_bread <= 70.0

    # 1 tbsp peanut butter ~ 16g
    food_pb, _, _ = match_ingredient_to_food("peanut butter")
    g_pb = convert_ingredient_to_grams(1.0, "tbsp", food_pb)
    assert 14.0 <= g_pb <= 18.0

    # 8 oz chicken breast ~ 226g
    food_chick, _, _ = match_ingredient_to_food("chicken breast")
    g_chick = convert_ingredient_to_grams(8.0, "oz", food_chick)
    assert 220.0 <= g_chick <= 230.0

    # 1 lb ground beef ~ 453.6g
    food_beef, _, _ = match_ingredient_to_food("ground beef")
    g_beef = convert_ingredient_to_grams(1.0, "lb", food_beef)
    assert 450.0 <= g_beef <= 460.0


@pytest.mark.django_db
def test_calculate_recipe_nutrition_pbj(auth_user):
    """Test full nutritional analysis on a PB&J sandwich."""
    user, _ = auth_user
    recipe = Recipe.objects.create(
        name="Test PB&J Sandwich",
        portions=1,
        created_by=user,
    )
    Ingredient.objects.create(recipe=recipe, name="bread", amount=Decimal("2.00"), amount_unit="slices")
    Ingredient.objects.create(recipe=recipe, name="peanut butter", amount=Decimal("1.00"), amount_unit="tbsp")
    Ingredient.objects.create(recipe=recipe, name="jam", amount=Decimal("1.00"), amount_unit="tbsp")

    result = calculate_recipe_nutrition(recipe)

    per_serving = result["per_serving"]
    # Expected PB&J: ~280 - 340 kcal, 8 - 12g protein, 40 - 50g carbs, 8 - 12g fat
    assert 270 <= per_serving["calories"] <= 350
    assert 7.0 <= per_serving["protein_g"] <= 14.0
    assert 35.0 <= per_serving["carbs_g"] <= 55.0
    assert 7.0 <= per_serving["fat_g"] <= 14.0

    macro_pct = result["macro_percentages"]
    assert macro_pct["protein_pct"] > 0
    assert macro_pct["carbs_pct"] > 0
    assert macro_pct["fat_pct"] > 0
    assert 98 <= (macro_pct["protein_pct"] + macro_pct["carbs_pct"] + macro_pct["fat_pct"]) <= 102

    assert len(result["ingredient_breakdown"]) == 3
    assert result["coverage"]["percent"] == 100


@pytest.mark.django_db
def test_update_recipe_nutrition_persists(auth_user):
    """Test update_recipe_nutrition persists values to Recipe fields."""
    user, _ = auth_user
    recipe = Recipe.objects.create(
        name="Test Chicken Rice Dish",
        portions=4,
        created_by=user,
    )
    Ingredient.objects.create(recipe=recipe, name="chicken breast", amount=Decimal("1.00"), amount_unit="lb")
    Ingredient.objects.create(recipe=recipe, name="white rice", amount=Decimal("2.00"), amount_unit="cups")
    Ingredient.objects.create(recipe=recipe, name="olive oil", amount=Decimal("1.00"), amount_unit="tbsp")

    update_recipe_nutrition(recipe, save=True)
    recipe.refresh_from_db()

    assert recipe.calories_per_serving > 0
    assert recipe.protein_per_serving_g > 15
    assert recipe.carbs_per_serving_g > 20
    assert recipe.fat_per_serving_g > 2
    assert recipe.has_nutrition is True
    assert recipe.total_calories > recipe.calories_per_serving
    assert recipe.nutrition_data["portions"] == 4


@pytest.mark.django_db
def test_filter_and_suggest_recipes_by_macro_goal(auth_user):
    """Test filtering and suggestions based on nutritional targets."""
    user, _ = auth_user
    # High protein recipe
    r_high_p = Recipe.objects.create(
        name="Grilled Chicken Feast",
        portions=2,
        calories_per_serving=450,
        protein_per_serving_g=Decimal("42.0"),
        carbs_per_serving_g=Decimal("10.0"),
        fat_per_serving_g=Decimal("8.0"),
        created_by=user,
    )
    # Low carb recipe
    r_low_carb = Recipe.objects.create(
        name="Keto Egg Skillet",
        portions=1,
        calories_per_serving=320,
        protein_per_serving_g=Decimal("18.0"),
        carbs_per_serving_g=Decimal("4.0"),
        fat_per_serving_g=Decimal("22.0"),
        created_by=user,
    )

    # Filter by protein
    high_p_results = filter_recipes_by_nutrition(min_protein=30)
    assert r_high_p in high_p_results
    assert r_low_carb not in high_p_results

    # Suggest high protein
    suggestions_p = suggest_recipes_by_macro_goal("high-protein", limit=5)
    assert r_high_p in suggestions_p

    # Suggest low carb
    suggestions_carb = suggest_recipes_by_macro_goal("low-carb", limit=5)
    assert r_low_carb in suggestions_carb


@pytest.mark.django_db
def test_recipe_view_page_renders_nutritional_analysis(client: Client, auth_user):
    """Test HTTP GET /recipes/<id>/ renders nutritional analysis section."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    recipe = Recipe.objects.create(
        name="Nutritious Salad Bowl",
        portions=2,
        calories_per_serving=350,
        protein_per_serving_g=Decimal("18.5"),
        carbs_per_serving_g=Decimal("28.0"),
        fat_per_serving_g=Decimal("12.0"),
        fiber_per_serving_g=Decimal("6.0"),
        sodium_per_serving_mg=420,
        nutrition_data={
            "portions": 2,
            "macro_percentages": {"protein_pct": 21, "carbs_pct": 32, "fat_pct": 47},
            "coverage": {"percent": 100},
            "ingredient_breakdown": [
                {
                    "name": "spinach",
                    "amount": 2.0,
                    "amount_unit": "cups",
                    "weight_g": 60.0,
                    "calories": 14,
                    "protein_g": 1.7,
                    "carbs_g": 2.2,
                    "fat_g": 0.2,
                    "matched": True,
                }
            ],
        },
        created_by=user,
    )

    resp = client.get(reverse("recipes:detail", args=[recipe.id]))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    # Check that the nutritional analysis section is present
    assert "Approximate Nutritional Analysis" in html
    assert "350" in html  # Calories
    assert "18.5" in html  # Protein
    assert "28.0" in html  # Carbs
    assert "12.0" in html  # Fat
    assert "420" in html  # Sodium
    assert "Caloric Distribution" in html
    assert "Per-Ingredient Nutritional Contribution" in html
    assert "spinach" in html
