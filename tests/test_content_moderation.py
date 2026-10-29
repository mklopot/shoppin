"""
Tests for Content Moderation & Anti-Profanity Enforcement.

Verifies that expletives, obscenities, slurs, and hurtful language are
strictly prohibited and blocked across all content creation paths (Recipes,
Ingredients, Shopping List Items, Meals, and Guidelines), while preserving
normal culinary vocabulary (e.g. shiitake, cocktail sauce, molasses).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.core.models import Workspace
from apps.core.services.moderation_service import (
    contains_obscene_language,
    validate_content_clean,
)
from apps.mealplans.models import Meal, MealPlan, MealPlanRule
from apps.recipes.models import Ingredient, Recipe
from apps.recipes.services.recipe_service import create_or_update_recipe
from apps.shopping.models import ShoppingList, ShoppingListItem

User = get_user_model()


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        username="chef_gordon",
        email="chef@example.com",
        password="secure_password_123",
    )
    return user


@pytest.fixture
def workspace_with_lists(db, auth_user):
    ws = Workspace.objects.create(name="Gordon's Kitchen", owner=auth_user)
    shop_list = ShoppingList.objects.create(name="Main Shopping List", workspace=ws, owner=auth_user)
    meal_plan = MealPlan.objects.create(name="Weekly Plan", workspace=ws, owner=auth_user)
    return ws, shop_list, meal_plan


# ---------------------------------------------------------------------------
# Unit Tests: Detection Engine & Culinary False Positive Prevention
# ---------------------------------------------------------------------------


def test_clean_culinary_terms_allowed():
    """Ensure standard culinary words and dishes do not trigger false positives."""
    culinary_phrases = [
        "Shiitake Mushroom Risotto",
        "Classic Shrimp Cocktail with Tangy Cocktail Sauce",
        "Rich Molasses Gingerbread Cake",
        "Pan-seared Chilean Sea Bass",
        "Fresh Lemongrass and Ginger Marinade",
        "Spotted Dick with Vanilla Custard",
        "Assorted Sweet Bell Peppers",
        "Peacock Farm Wildflower Honey",
        "Homestyle Butter Chicken",
        "Spaghetti Bolognese with Parmigiano-Reggiano",
        "Tarragon Mustard Roast Chicken",
        "San Marzano Passata Di Pomodoro",
        "Pinch of sea salt and cracked black pepper",
    ]
    for phrase in culinary_phrases:
        is_obscene, word = contains_obscene_language(phrase)
        assert not is_obscene, f"False positive on '{phrase}'! (detected '{word}')"
        validate_content_clean(phrase, field_label="Food test")


def test_expletives_and_slurs_detected():
    """Verify that profanity, slurs, masked evasions, and hurtful phrases are blocked."""
    prohibited_samples = [
        "What the fuck is this recipe",
        "This taste like shit",
        "bitch please add more garlic",
        "You complete asshole",
        "f*ck",
        "f**k",
        "f.u.c.k",
        "sh!t",
        "sh*t",
        "sh1t",
        "b!tch",
        "b*tch",
        "a$$hole",
        "cunt",
        "c*nt",
        "motherfucker",
        "bastard",
        "faggot",
        "nigger",
        "n*gger",
        "retarded recipe",
        "kill yourself",
        "kys",
        "go die",
    ]
    for phrase in prohibited_samples:
        is_obscene, word = contains_obscene_language(phrase)
        assert is_obscene, f"Failed to detect prohibited language in '{phrase}'"
        with pytest.raises(ValidationError):
            validate_content_clean(phrase, field_label="Sample")


# ---------------------------------------------------------------------------
# Recipe & Ingredient Moderation Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_recipe_with_expletive_name_blocked(auth_user):
    """Attempting to create a recipe with an expletive in its name raises ValidationError."""
    recipe_data = {
        "name": "Fucking Delicious Pasta",
        "description": "A very savory dish.",
        "directions": "Boil noodles. Eat.",
    }
    with pytest.raises(ValidationError):
        create_or_update_recipe(recipe_data, user=auth_user)

    assert not Recipe.objects.filter(name__icontains="Fucking").exists()


@pytest.mark.django_db
def test_create_recipe_with_expletive_directions_blocked(auth_user):
    """Attempting to create a recipe with profanity in instructions is blocked."""
    recipe_data = {
        "name": "Savory Garlic Soup",
        "description": "A tasty broth.",
        "directions": "Stir the pot and don't be an asshole.",
    }
    with pytest.raises(ValidationError):
        create_or_update_recipe(recipe_data, user=auth_user)

    assert not Recipe.objects.filter(name="Savory Garlic Soup").exists()


@pytest.mark.django_db
def test_create_recipe_with_expletive_ingredient_blocked(auth_user):
    """Attempting to create a recipe containing an expletive ingredient is blocked."""
    recipe_data = {
        "name": "Spicy Chili",
        "description": "Slow cooked chili.",
        "directions": "Simmer for 2 hours.",
        "ingredient_name[]": ["2 lbs ground beef", "1 can of shit beans"],
        "ingredient_amount[]": ["2", "1"],
    }
    with pytest.raises(ValidationError):
        create_or_update_recipe(recipe_data, user=auth_user)

    assert not Recipe.objects.filter(name="Spicy Chili").exists()


@pytest.mark.django_db
def test_ingredient_orm_creation_intercepted_by_signal():
    """Direct ORM creation of an Ingredient with an expletive is aborted by pre_save signal."""
    recipe = Recipe.objects.create(name="Clean Stew")
    with pytest.raises(ValidationError):
        Ingredient.objects.create(recipe=recipe, name="1 cup of bullshit")

    assert not Ingredient.objects.filter(name__icontains="bullshit").exists()


@pytest.mark.django_db
def test_recipe_create_view_displays_user_error_on_expletive(client: Client, auth_user):
    """Submitting recipe creation form with expletives returns an error message and halts creation."""
    client.force_login(auth_user)
    post_data = {
        "name": "Bullshit Casserole",
        "description": "Nobody likes this.",
        "directions": "Bake at 350F.",
    }
    response = client.post(reverse("recipes:create"), post_data, follow=True)
    assert response.status_code == 200
    content = response.content.decode()
    assert "contains prohibited obscene or hurtful language" in content
    assert not Recipe.objects.filter(name="Bullshit Casserole").exists()


# ---------------------------------------------------------------------------
# Shopping List Moderation Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_add_shopping_item_with_expletive_blocked_in_view(client: Client, auth_user, workspace_with_lists):
    """Adding a shopping list item with profanity returns an error toast and does not save."""
    client.force_login(auth_user)
    post_data = {
        "name": "sh!t paper",
        "amount": "1",
        "category": "Household",
    }
    response = client.post(reverse("shopping:add_item"), post_data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Obscene or hurtful language is not permitted" in content
    assert not ShoppingListItem.objects.filter(name__icontains="sh!t").exists()


@pytest.mark.django_db
def test_shopping_item_orm_save_intercepted_by_signal(workspace_with_lists):
    """Direct ORM creation of a ShoppingListItem with expletive is aborted by pre_save signal."""
    _, shop_list, _ = workspace_with_lists
    with pytest.raises(ValidationError):
        ShoppingListItem.objects.create(
            shopping_list=shop_list,
            name="bag of dicks",
            amount=1,
        )

    assert not ShoppingListItem.objects.filter(name__icontains="dicks").exists()


# ---------------------------------------------------------------------------
# Meal Plan & Rule Moderation Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_add_meal_with_expletive_blocked(client: Client, auth_user, workspace_with_lists):
    """Adding a meal with an expletive in the name is intercepted and rejected."""
    client.force_login(auth_user)
    post_data = {"meal": "bitchin dinner"}
    response = client.post(reverse("mealplans:add_meal"), post_data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Obscene or hurtful language is not permitted" in content
    assert not Meal.objects.filter(name__icontains="bitchin").exists()


@pytest.mark.django_db
def test_add_meal_rule_with_hurtful_language_blocked(client: Client, auth_user, workspace_with_lists):
    """Adding a dietary guideline containing abusive or hurtful phrasing is rejected."""
    client.force_login(auth_user)
    post_data = {"rule_text": "eat healthy or go die"}
    response = client.post(reverse("mealplans:add_rule"), post_data)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Obscene or hurtful language is not permitted" in content
    assert not MealPlanRule.objects.filter(rule_text__icontains="go die").exists()


@pytest.mark.django_db
def test_meal_orm_creation_intercepted_by_signal(workspace_with_lists):
    """Direct ORM creation of a Meal with an expletive is aborted by pre_save signal."""
    _, _, meal_plan = workspace_with_lists
    with pytest.raises(ValidationError):
        Meal.objects.create(
            meal_plan=meal_plan,
            name="Motherfucking Lunch",
        )

    assert not Meal.objects.filter(name__icontains="Motherfucking").exists()
