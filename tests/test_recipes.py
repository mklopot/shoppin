"""
Unit and integration tests for culinary recipes:
models, search service, ratings, and views.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.recipes.models import Ingredient, Recipe, RecipeRating
from apps.recipes.services.recipe_service import (
    add_recipe_to_shopping_list,
    create_or_update_recipe,
    get_filter_options,
    search_recipes,
    submit_recipe_rating,
)
from apps.shopping.models import ShoppingList

User = get_user_model()


@pytest.fixture
def sample_recipes(db, auth_user):
    user, _ = auth_user

    r1 = Recipe.objects.create(
        name="Classic Tacos",
        description="Crispy beef tacos with fresh salsa.",
        directions="1. Brown ground beef.\n2. Fill taco shells.\n3. Top with salsa.",
        cuisine="Mexican",
        dish_type="Sandwich",
        difficulty_level="easy",
        portions=4,
        prep_time_minutes=15,
        cook_time_minutes=10,
        dietary_restrictions=["Dairy-Free"],
        meal_type=["Dinner", "Lunch"],
        occasions=["Party / BBQ", "Weeknight Fast"],
        special_equipment=["Cast Iron Skillet"],
        storage_instructions="Store filling separately.",
        reheating_instructions="Reheat filling in skillet.",
        photo_urls=["https://example.com/tacos.jpg"],
        bibliography=["Authentic Mexican by Rick Bayless"],
        created_by=user,
    )
    Ingredient.objects.create(recipe=r1, name="Ground Beef", amount=Decimal("1.00"), amount_unit="lb", order=0)
    Ingredient.objects.create(recipe=r1, name="Taco Shells", amount=Decimal("8.00"), amount_unit="count", order=1)
    Ingredient.objects.create(recipe=r1, name="Salsa", amount=Decimal("1.00"), amount_unit="cup", optional=True, order=2)

    r2 = Recipe.objects.create(
        name="Vegetarian Lasagna",
        description="Layered pasta with ricotta and spinach.",
        directions="1. Cook noodles.\n2. Layer ricotta, noodles, spinach, and marinara.\n3. Bake 40 mins.",
        cuisine="Italian",
        dish_type="Casserole",
        difficulty_level="medium",
        portions=8,
        prep_time_minutes=30,
        cook_time_minutes=45,
        dietary_restrictions=["Vegetarian", "Kosher (Dairy)"],
        meal_type=["Dinner"],
        occasions=["Christmas", "Winter"],
        special_equipment=["Casserole Dish", "Oven"],
        storage_instructions="Refrigerate up to 4 days.",
        reheating_instructions="Bake covered at 350°F.",
        photo_urls=["https://example.com/lasagna.jpg"],
        created_by=user,
    )
    Ingredient.objects.create(recipe=r2, name="Lasagna Noodles", amount=Decimal("12.00"), amount_unit="count", order=0)
    Ingredient.objects.create(recipe=r2, name="Ricotta Cheese", amount=Decimal("15.00"), amount_unit="oz", order=1)
    Ingredient.objects.create(recipe=r2, name="Spinach", amount=Decimal("10.00"), amount_unit="oz", order=2)

    r3 = Recipe.objects.create(
        name="Instant Pot Beef Brisket",
        description="Tender braised brisket cooked quickly under pressure.",
        directions="1. Sear brisket.\n2. Add onions and broth.\n3. Cook on High Pressure for 75 mins.",
        cuisine="American",
        dish_type="Stew",
        difficulty_level="hard",
        portions=6,
        prep_time_minutes=20,
        cook_time_minutes=75,
        dietary_restrictions=["Gluten-Free", "Dairy-Free"],
        meal_type=["Dinner"],
        occasions=["Christmas", "Party / BBQ"],
        special_equipment=["Instant Pot"],
        created_by=user,
    )
    Ingredient.objects.create(recipe=r3, name="Beef Brisket", amount=Decimal("3.00"), amount_unit="lb", order=0)
    Ingredient.objects.create(recipe=r3, name="Beef Broth", amount=Decimal("2.00"), amount_unit="cup", order=1)

    return r1, r2, r3


# ---------------------------------------------------------------------------
# 1. Model & Property Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_model_properties(sample_recipes, auth_user):
    user, _ = auth_user
    r1, _, _ = sample_recipes

    assert r1.primary_photo_url == "https://example.com/tacos.jpg"
    assert r1.total_time_minutes == 25
    assert len(r1.directions_steps) == 3
    assert r1.directions_steps[0] == "1. Brown ground beef."
    assert r1.average_rating is None
    assert r1.rating_count == 0

    # Add rating
    RecipeRating.objects.create(recipe=r1, user=user, stars=5, thumbs_up=True)
    assert r1.average_rating == 5.0
    assert r1.rating_count == 1
    assert r1.thumbs_up_count == 1


# ---------------------------------------------------------------------------
# 2. Search & Filtering Service Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_search_recipes_free_text(sample_recipes):
    r1, r2, r3 = sample_recipes

    # Search by recipe name
    res = search_recipes({"q": "tacos"})
    assert list(res) == [r1]

    # Search by ingredient name
    res = search_recipes({"q": "ricotta"})
    assert list(res) == [r2]

    # Search by equipment
    res = search_recipes({"q": "instant pot"})
    assert r3 in res

    # Search empty returns all
    res = search_recipes({})
    assert len(res) == 3


@pytest.mark.django_db
def test_search_recipes_facets(sample_recipes):
    r1, r2, r3 = sample_recipes

    # Filter by cuisine
    assert list(search_recipes({"cuisine": "Mexican"})) == [r1]
    assert list(search_recipes({"cuisine": "Italian"})) == [r2]

    # Filter by dish_type
    assert list(search_recipes({"dish_type": "Casserole"})) == [r2]

    # Filter by difficulty
    assert list(search_recipes({"difficulty": "easy"})) == [r1]
    assert list(search_recipes({"difficulty": "hard"})) == [r3]

    # Filter by dietary restriction
    assert list(search_recipes({"dietary": "Vegetarian"})) == [r2]
    assert r1 in search_recipes({"dietary": "Dairy-Free"})
    assert r3 in search_recipes({"dietary": "Dairy-Free"})

    # Filter by occasion
    assert r1 in search_recipes({"occasion": "Party / BBQ"})
    assert r3 in search_recipes({"occasion": "Party / BBQ"})
    assert list(search_recipes({"occasion": "Winter"})) == [r2]

    # Filter by equipment
    assert list(search_recipes({"equipment": "Instant Pot"})) == [r3]
    assert list(search_recipes({"equipment": "Casserole Dish"})) == [r2]


@pytest.mark.django_db
def test_search_recipes_multi_include_and_exclude(sample_recipes, auth_user):
    user, _ = auth_user
    r1, r2, r3 = sample_recipes

    # Add r4: Kosher + Vegan Main dish
    r4 = Recipe.objects.create(
        name="Kosher Parve Chickpea Stew",
        description="Hearty Middle Eastern chickpea dish.",
        directions="1. Simmer chickpeas with cumin.",
        cuisine="Middle Eastern",
        dish_type="Main",
        difficulty_level="easy",
        portions=4,
        dietary_restrictions=["Vegan", "Kosher (Parve)", "Gluten-Free"],
        meal_type=["Dinner"],
        occasions=["Weeknight Fast"],
        special_equipment=["Slow Cooker"],
        created_by=user,
    )

    # 1. Multi-value inclusion with OR logic within the same attribute: "Main" or "Stew"
    dish_results = list(search_recipes({"include_dish_type": ["Main", "Stew"]}))
    assert len(dish_results) == 2
    assert r3 in dish_results  # r3 is Stew
    assert r4 in dish_results  # r4 is Main
    assert r1 not in dish_results  # r1 is Sandwich
    assert r2 not in dish_results  # r2 is Casserole

    # Also test comma-separated inclusion string
    comma_results = list(search_recipes({"include_dish_type": "Main, Stew"}))
    assert set(comma_results) == {r3, r4}

    # 2. Attribute inclusion + exclusion: Include "Kosher", Exclude "Vegan"
    # r2 has ["Vegetarian", "Kosher (Dairy)"] -> Matches Kosher, not Vegan -> Included
    # r4 has ["Vegan", "Kosher (Parve)", "Gluten-Free"] -> Matches Kosher, BUT has Vegan -> Excluded
    diet_results = list(search_recipes({"include_dietary": ["Kosher"], "exclude_dietary": ["Vegan"]}))
    assert diet_results == [r2]

    # 3. Combined inclusion across multiple attributes with exclusions
    # Include cuisines Mexican or Italian, exclude dish_type Casserole
    multi_results = list(search_recipes({
        "include_cuisine": ["Mexican", "Italian"],
        "exclude_dish_type": ["Casserole"],
    }))
    assert multi_results == [r1]  # r2 is Casserole, so excluded; r1 is Mexican Sandwich, so included

    # 4. Exclusion taking precedence if a value is in both include and exclude
    conflict_results = list(search_recipes({
        "include_dish_type": ["Stew"],
        "exclude_dish_type": ["Stew"],
    }))
    assert r3 not in conflict_results


@pytest.mark.django_db
def test_recipe_list_view_multi_filters_htmx(client: Client, sample_recipes, auth_user):
    user, _ = auth_user
    client.force_login(user)

    # Request with multi-facet GET parameters via HTMX partial swap
    url = reverse("recipes:list")
    resp = client.get(
        url,
        {
            "include_dish_type": ["Casserole", "Stew"],
            "exclude_dietary": ["Vegetarian"],
        },
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Should contain r3 (Beef Brisket Stew), but not r2 (Lasagna Casserole is Vegetarian)
    assert "Instant Pot Beef Brisket" in content
    assert "Vegetarian Lasagna" not in content

    # Should render active inclusion and exclusion badges
    assert "Dish: Casserole" in content
    assert "Dish: Stew" in content
    assert "NOT Diet: Vegetarian" in content


@pytest.mark.django_db
def test_search_recipes_sorting(sample_recipes, auth_user):
    user, _ = auth_user
    r1, r2, r3 = sample_recipes

    # Give r2 top rating
    RecipeRating.objects.create(recipe=r2, user=user, stars=5, thumbs_up=True)
    RecipeRating.objects.create(recipe=r1, user=user, stars=3, thumbs_up=True)

    res = list(search_recipes({"sort": "rating"}))
    assert res[0] == r2
    assert res[1] == r1

    # Sort by prep time (r1=15, r3=20, r2=30)
    res_time = list(search_recipes({"sort": "time"}))
    assert res_time[0] == r1
    assert res_time[1] == r3
    assert res_time[2] == r2


@pytest.mark.django_db
def test_get_filter_options(sample_recipes):
    options = get_filter_options()
    assert "Mexican" in options["cuisines"]
    assert "Italian" in options["cuisines"]
    assert "Casserole" in options["dish_types"]
    assert "Vegetarian" in options["dietary_options"]
    assert "Instant Pot" in options["equipment_options"]


# ---------------------------------------------------------------------------
# 3. Create, Update & Rating Services
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_and_update_recipe(auth_user):
    user, _ = auth_user

    data = {
        "name": "Guacamole Dip",
        "description": "Zesty avocado dip.",
        "directions": "1. Mash avocados.\n2. Stir in lime juice and salt.",
        "cuisine": "Mexican",
        "dish_type": "Appetizer",
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 10,
        "cook_time_minutes": 0,
        "dietary_restrictions": ["Vegan", "Gluten-Free"],
        "meal_type": ["Snack", "Appetizer"],
        "occasions": ["Party / BBQ"],
        "special_equipment": ["Bowl"],
        "storage_instructions": "Cover tightly with plastic wrap touching the surface.",
        "reheating_instructions": "Serve chilled.",
        "photo_url": "https://example.com/guac.jpg",
        "ingredient_name[]": ["Avocados", "Lime Juice", "Salt"],
        "ingredient_amount[]": ["3", "1", "0.5"],
        "ingredient_unit[]": ["count", "tbsp", "tsp"],
        "ingredient_optional[]": ["0", "0", "1"],
        "ingredient_brand[]": ["Haas", "", ""],
        "ingredient_vendor[]": ["Trader Joe's", "", ""],
    }

    recipe = create_or_update_recipe(data, user=user)
    assert recipe.name == "Guacamole Dip"
    assert recipe.cuisine == "Mexican"
    assert recipe.ingredients.count() == 3
    assert recipe.ingredients.filter(name="Avocados").first().brand == "Haas"

    # Now edit recipe
    edit_data = {
        "name": "Super Guacamole Dip",
        "description": "Updated zesty avocado dip with cilantro.",
        "directions": "1. Mash avocados.\n2. Add cilantro and lime.",
        "cuisine": "Mexican",
        "dish_type": "Appetizer",
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 12,
        "cook_time_minutes": 0,
        "dietary_restrictions": ["Vegan", "Gluten-Free"],
        "meal_type": ["Snack"],
        "occasions": ["Party / BBQ"],
        "special_equipment": [],
        "storage_instructions": "Keep cold.",
        "reheating_instructions": "",
        "photo_url": "https://example.com/guac2.jpg",
        "ingredient_name[]": ["Avocados", "Cilantro"],
        "ingredient_amount[]": ["4", "0.25"],
        "ingredient_unit[]": ["count", "cup"],
        "ingredient_optional[]": ["0", "1"],
    }
    updated = create_or_update_recipe(edit_data, recipe_id=recipe.id, user=user)
    assert updated.id == recipe.id
    assert updated.name == "Super Guacamole Dip"
    assert updated.portions == 6
    assert updated.ingredients.count() == 2


@pytest.mark.django_db
def test_recipe_photo_upload_and_clear(auth_user):
    user, _ = auth_user

    # Minimal valid 1x1 GIF
    gif_bytes = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    uploaded = SimpleUploadedFile("homemade_pizza.gif", gif_bytes, content_type="image/gif")

    data = {
        "name": "Homemade Pizza",
        "cuisine": "Italian",
        "dish_type": "Main",
        "difficulty_level": "medium",
        "portions": 4,
    }

    # 1. Create with uploaded file
    recipe = create_or_update_recipe(data, files={"photo_file": uploaded}, user=user)
    assert bool(recipe.photo_file) is True
    assert "homemade_pizza" in recipe.photo_file.name
    assert recipe.primary_photo_url.startswith(recipe.photo_file.url)

    # 2. Clear photo on edit
    clear_data = {
        "name": "Homemade Pizza",
        "clear_photo": "1",
    }
    updated = create_or_update_recipe(clear_data, recipe_id=recipe.id, user=user)
    assert bool(updated.photo_file) is False
    assert updated.primary_photo_url == ""


@pytest.mark.django_db
def test_recipe_public_slider_creation_and_moderation(auth_user):
    user, _ = auth_user

    # 1. Create a private recipe via toggle (is_public=0)
    priv_data = {
        "name": "Grandma's Secret Dressing",
        "cuisine": "American",
        "dish_type": "Sauce",
        "has_public_toggle": "1",
        "is_public": "0",
    }
    priv_recipe = create_or_update_recipe(priv_data, user=user)
    assert priv_recipe.is_public is False
    assert priv_recipe.is_approved is False

    # 2. Create a public recipe as regular user (is_public=1) -> requires moderator approval
    pub_data = {
        "name": "World Famous Tomato Soup",
        "cuisine": "American",
        "dish_type": "Soup",
        "has_public_toggle": "1",
        "is_public": "1",
    }
    pub_recipe = create_or_update_recipe(pub_data, user=user)
    assert pub_recipe.is_public is True
    assert pub_recipe.is_approved is False  # Regular user submissions require moderator review

    # 3. Create a public recipe as staff user -> automatically approved
    staff_user = User.objects.create_user(username="mod_chef", password="pw", is_staff=True)
    staff_recipe = create_or_update_recipe(
        {
            "name": "Staff Approved French Toast",
            "cuisine": "French",
            "dish_type": "Breakfast",
            "has_public_toggle": "1",
            "is_public": "1",
        },
        user=staff_user,
    )
    assert staff_recipe.is_public is True
    assert staff_recipe.is_approved is True


@pytest.mark.django_db
def test_recipe_form_renders_public_slider_and_modal(client: Client, auth_user):
    user, _ = auth_user
    client.force_login(user)

    url = reverse("recipes:create")
    resp = client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Check slider input and label
    assert 'name="is_public"' in content
    assert 'has_public_toggle' in content
    assert "Make this recipe public" in content

    # Check info circle and modal dialog
    assert "togglePublicRecipeModal" in content
    assert "public-recipe-info-modal" in content
    assert "Public Recipe Visibility" in content
    assert "approved by moderators" in content
    assert "may be edited" in content


@pytest.mark.django_db
def test_recipe_form_ingredient_enter_key_and_cleanup_script(client: Client, auth_user):
    user, _ = auth_user
    client.force_login(user)

    url = reverse("recipes:create")
    resp = client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    # Check ingredient table and dynamic keyboard handlers
    assert 'id="ingredients-table-body"' in content
    assert "handleIngredientKeydown" in content
    assert "cleanupEmptyIngredientRows" in content
    assert "initIngredientEnterBehavior" in content
    assert "addIngredientRow" in content

    # Test recipe creation where a trailing empty ingredient row was submitted
    post_data = {
        "name": "Chili Con Carne",
        "directions": "Cook beef and spices thoroughly.",
        "portions": 4,
        "ingredient_name[]": ["Ground Beef", "Kidney Beans", ""],
        "ingredient_amount[]": ["1 lb", "1 can", "1"],
        "ingredient_unit[]": ["", "", ""],
        "ingredient_optional[]": ["0", "0", "0"],
        "ingredient_brand[]": ["", "", ""],
        "ingredient_vendor[]": ["", "", ""],
    }
    post_resp = client.post(url, post_data)
    assert post_resp.status_code == 302
    created = Recipe.objects.get(name="Chili Con Carne")
    assert created.ingredients.count() == 2
    assert list(created.ingredients.values_list("name", flat=True)) == ["Ground Beef", "Kidney Beans"]


@pytest.mark.django_db
def test_submit_recipe_rating(sample_recipes, auth_user):
    user, _ = auth_user
    r1, _, _ = sample_recipes

    rating = submit_recipe_rating(r1, user, stars=4, thumbs_up=True)
    assert rating.stars == 4
    assert rating.thumbs_up is True

    # Update rating
    updated_rating = submit_recipe_rating(r1, user, stars=5, thumbs_up=False)
    assert updated_rating.stars == 5
    assert updated_rating.thumbs_up is False
    assert RecipeRating.objects.filter(recipe=r1, user=user).count() == 1


# ---------------------------------------------------------------------------
# 4. Shopping List Addition & Duplicate Combining
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_add_recipe_to_shopping_list(sample_recipes, auth_user):
    user, workspace = auth_user
    r1, _, _ = sample_recipes
    shopping_list = ShoppingList.objects.create(name="Weekly List", workspace=workspace)

    # 1. Add recipe ingredients
    added = add_recipe_to_shopping_list(r1, shopping_list)
    assert len(added) == 3
    assert shopping_list.items.count() == 3

    beef_item = shopping_list.items.get(name="Ground Beef")
    assert beef_item.amount == Decimal("1.00")
    assert beef_item.amount_unit == "lb"
    assert beef_item.purpose == "Classic Tacos"  # clean purpose without duplicate 'For'
    assert beef_item.locked is False

    # 2. Lock beef item as confirmed
    beef_item.locked = True
    beef_item.save()

    # 3. Add same recipe again -> should combine amount to 2 lb, unlock to False, and clean purpose
    add_recipe_to_shopping_list(r1, shopping_list)
    assert shopping_list.items.count() == 3  # not duplicated!

    beef_item.refresh_from_db()
    assert beef_item.amount == Decimal("2.00")
    assert beef_item.locked is False  # reset to not confirmed status because amount increased


# ---------------------------------------------------------------------------
# 5. Views & HTTP Endpoints Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_recipe_views(client: Client, sample_recipes, auth_user):
    user, workspace = auth_user
    r1, r2, r3 = sample_recipes
    client.force_login(user)

    # Set active workspace in session
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    # List view standard GET
    resp = client.get(reverse("recipes:list"))
    assert resp.status_code == 200
    list_content = resp.content.decode("utf-8")
    assert "Classic Tacos" in list_content
    assert "Vegetarian Lasagna" in list_content
    assert "resetRecipeFilters()" in list_content
    assert 'id="recipe-reset-btn"' in list_content
    # Verify meals dropdown is NOT displayed on the quick view cards
    assert 'name="meal_id"' not in list_content
    assert reverse("recipes:prompt_add_to_mealplan", args=[r1.id]) in list_content

    # Prompt add to meal plan modal GET
    resp_prompt = client.get(reverse("recipes:prompt_add_to_mealplan", args=[r1.id]), HTTP_HX_REQUEST="true")
    assert resp_prompt.status_code == 200
    prompt_html = resp_prompt.content.decode("utf-8")
    assert "Add to Meal Plan" in prompt_html
    assert "Classic Tacos" in prompt_html
    assert 'name="meal_id"' in prompt_html

    # List view HTMX filter GET
    resp_htmx = client.get(
        reverse("recipes:list") + "?q=lasagna",
        HTTP_HX_REQUEST="true",
    )
    assert resp_htmx.status_code == 200
    html = resp_htmx.content.decode("utf-8")
    assert "Vegetarian Lasagna" in html
    assert "Classic Tacos" not in html
    assert "Clear all filters" in html
    assert "resetRecipeFilters()" in html
    assert "clearSingleRecipeFilter('q')" in html

    # Empty search state has Reset Filters button calling resetRecipeFilters()
    resp_empty = client.get(
        reverse("recipes:list") + "?q=nonexistentdish9999",
        HTTP_HX_REQUEST="true",
    )
    assert resp_empty.status_code == 200
    empty_html = resp_empty.content.decode("utf-8")
    assert "No matching recipes found" in empty_html
    assert "Reset Filters" in empty_html
    assert "resetRecipeFilters()" in empty_html

    # Detail view standard GET
    resp_detail = client.get(reverse("recipes:detail", args=[r1.id]))
    assert resp_detail.status_code == 200
    assert "Classic Tacos" in resp_detail.content.decode("utf-8")

    # Detail view HTMX modal
    resp_modal = client.get(
        reverse("recipes:detail", args=[r1.id]) + "?modal=1",
        HTTP_HX_REQUEST="true",
    )
    assert resp_modal.status_code == 200
    assert "View Full Recipe" in resp_modal.content.decode("utf-8")

    # Rating POST
    resp_rate = client.post(
        reverse("recipes:rate", args=[r1.id]),
        {"stars": 5, "thumbs_up": "true"},
    )
    assert resp_rate.status_code == 200
    assert RecipeRating.objects.filter(recipe=r1, user=user).exists()

    # Add to meal plan creating a new meal entry
    resp_plan = client.post(
        reverse("recipes:add_to_mealplan", args=[r1.id]),
        {"meal_id": "new", "meal_name": "Friday Fiesta"},
    )
    assert resp_plan.status_code == 200
    assert "Classic Tacos" in resp_plan.content.decode("utf-8")
    assert "Friday Fiesta" in resp_plan.content.decode("utf-8")

    # Verify meal was created and ingredients synchronized to shopping list
    meal_plan = workspace.get_meal_plan()
    assert meal_plan.meals.filter(name="Friday Fiesta").exists()
    shopping_list = workspace.get_primary_list()
    assert shopping_list.items.filter(name="Ground Beef").exists()

    # Create recipe with photo upload POST
    gif_bytes = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    upload_file = SimpleUploadedFile("tasty_soup.gif", gif_bytes, content_type="image/gif")
    resp_create = client.post(
        reverse("recipes:create"),
        {
            "name": "Tasty Soup",
            "cuisine": "American",
            "dish_type": "Soup",
            "portions": 4,
            "photo_file": upload_file,
        },
    )
    assert resp_create.status_code == 302
    created_soup = Recipe.objects.get(name="Tasty Soup")
    assert bool(created_soup.photo_file) is True

    # Delete recipe POST
    resp_del = client.post(reverse("recipes:delete", args=[r3.id]))
    assert resp_del.status_code == 302
    assert not Recipe.objects.filter(id=r3.id).exists()


MOCK_RECIPE_HTML = """
<!DOCTYPE html>
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Classic Guacamole",
  "description": "Authentic homemade fresh guacamole.",
  "recipeYield": "6 servings",
  "prepTime": "PT10M",
  "cookTime": "PT5M",
  "totalTime": "PT15M",
  "recipeIngredient": [
    "3 ripe avocados",
    "1/2 cup diced red onion",
    "2 tbsp fresh lime juice",
    "1/2 tsp kosher salt",
    "1 (15-ounce) can diced tomatoes",
    "salt and pepper to taste"
  ],
  "recipeInstructions": [
    {"@type": "HowToStep", "text": "Cut avocados and scoop into bowl."},
    {"@type": "HowToStep", "text": "Mash avocados with lime juice and salt."},
    {"@type": "HowToStep", "text": "Fold in diced onion and tomatoes, then serve."}
  ],
  "image": "https://images.example.com/guac.jpg",
  "recipeCategory": "Appetizer",
  "recipeCuisine": "Mexican"
}
</script>
</head>
<body><h1>Classic Guacamole</h1></body>
</html>
"""


def test_parse_ingredient_line():
    """Verify parsing of various free-form ingredient text lines into structured tokens."""
    from apps.recipes.services.recipe_scraper import parse_ingredient_line

    # 1. Whole number without unit
    i1 = parse_ingredient_line("3 ripe avocados")
    assert i1["amount"] == Decimal("3.00")
    assert i1["amount_unit"] == ""
    assert i1["name"] == "ripe avocados"

    # 2. Simple fraction with unit
    i2 = parse_ingredient_line("1/2 cup diced red onion")
    assert i2["amount"] == Decimal("0.50")
    assert i2["amount_unit"] == "cup"
    assert i2["name"] == "diced red onion"

    # 3. Tablespoon unit
    i3 = parse_ingredient_line("2 tbsp fresh lime juice")
    assert i3["amount"] == Decimal("2.00")
    assert i3["amount_unit"] == "tbsp"
    assert i3["name"] == "fresh lime juice"

    # 4. Mixed fraction
    i4 = parse_ingredient_line("1 1/2 cups of flour")
    assert i4["amount"] == Decimal("1.50")
    assert i4["amount_unit"] == "cups"
    assert i4["name"] == "flour"

    # 5. Parenthesized can size
    i5 = parse_ingredient_line("1 (15-ounce) can diced tomatoes")
    assert i5["amount"] == Decimal("1.00")
    assert i5["amount_unit"] == "can"
    assert "(15-ounce) diced tomatoes" in i5["name"]

    # 6. Unicode fraction
    i6 = parse_ingredient_line("½ tsp salt")
    assert i6["amount"] == Decimal("0.50")
    assert i6["amount_unit"] == "tsp"
    assert i6["name"] == "salt"

    # 7. Non-numeric line
    i7 = parse_ingredient_line("salt and pepper to taste")
    assert i7["amount"] == Decimal("1.00")
    assert i7["name"] == "salt and pepper to taste"


def test_scrape_recipe_data_from_mock_html():
    """Test scrape_recipe_data extracts all fields accurately from Schema.org HTML."""
    from apps.recipes.services.recipe_scraper import scrape_recipe_data

    url = "https://www.allrecipes.com/recipe/158968/classic-guacamole/"
    data = scrape_recipe_data(url=url, html=MOCK_RECIPE_HTML)

    assert data["name"] == "Classic Guacamole"
    assert data["description"] == "Authentic homemade fresh guacamole."
    assert data["portions"] == 6
    assert data["prep_time_minutes"] == 10
    assert data["cook_time_minutes"] == 5
    assert data["cuisine"] == "Mexican"
    assert data["dish_type"] == "Appetizer"
    assert data["photo_url"] == "https://images.example.com/guac.jpg"
    assert len(data["ingredients"]) == 6
    assert "Mash avocados" in data["directions"]
    assert data["domain"] == "www.allrecipes.com"


@pytest.mark.django_db
def test_import_recipe_from_url_service(auth_user):
    """Test import_recipe_from_url creates Recipe and Ingredients in the database."""
    from apps.recipes.services.recipe_scraper import import_recipe_from_url

    user, _ = auth_user
    url = "https://www.allrecipes.com/recipe/158968/classic-guacamole/"
    recipe = import_recipe_from_url(url=url, user=user, html=MOCK_RECIPE_HTML)

    assert recipe.id is not None
    assert recipe.name == "Classic Guacamole"
    assert recipe.portions == 6
    assert recipe.prep_time_minutes == 10
    assert recipe.cook_time_minutes == 5
    assert recipe.cuisine == "Mexican"
    assert recipe.photo_urls == ["https://images.example.com/guac.jpg"]
    assert recipe.bibliography == [url]
    assert recipe.created_by == user
    assert recipe.is_web_imported is True
    assert recipe.copyright_cleared is False
    assert recipe.is_public is False
    assert recipe.is_approved is False
    assert recipe.is_locked_from_public is True
    assert recipe.can_be_made_public(user) is False

    # Check ingredients created in DB
    ings = list(recipe.ingredients.all())
    assert len(ings) == 6
    assert any(i.name == "ripe avocados" and i.amount == Decimal("3.00") for i in ings)
    assert any(i.name == "diced red onion" and i.amount_unit == "cup" for i in ings)

    # Importing same URL again avoids duplicate name collision by incrementing suffix
    recipe2 = import_recipe_from_url(url=url, user=user, html=MOCK_RECIPE_HTML)
    assert recipe2.name == "Classic Guacamole (1)"


@pytest.mark.django_db
def test_recipe_import_url_view_direct(client: Client, auth_user, monkeypatch):
    """Test POST to /recipes/import-url/ with action='direct' imports recipe and redirects."""
    from unittest.mock import MagicMock

    import requests

    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    mock_resp = MagicMock()
    mock_resp.text = MOCK_RECIPE_HTML
    mock_resp.is_redirect = False
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: mock_resp)

    resp = client.post(
        reverse("recipes:import_url"),
        {
            "url": "https://www.allrecipes.com/recipe/158968/classic-guacamole/",
            "action": "direct",
        },
    )
    assert resp.status_code == 302
    created = Recipe.objects.get(name="Classic Guacamole")
    assert resp.url == created.get_absolute_url()
    assert created.ingredients.count() == 6
    assert created.is_web_imported is True
    assert created.copyright_cleared is False
    assert created.is_public is False


@pytest.mark.django_db
def test_recipe_create_view_with_import_url_prefill(client: Client, auth_user, monkeypatch):
    """Test GET /recipes/create/?import_url=... renders form pre-filled with scraped recipe data."""
    from unittest.mock import MagicMock

    import requests

    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    mock_resp = MagicMock()
    mock_resp.text = MOCK_RECIPE_HTML
    mock_resp.is_redirect = False
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: mock_resp)

    url = "https://www.allrecipes.com/recipe/158968/classic-guacamole/"
    resp = client.get(reverse("recipes:create") + f"?import_url={url}")
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    assert "Classic Guacamole" in html
    assert "Authentic homemade fresh guacamole" in html
    assert "ripe avocados" in html
    assert "diced red onion" in html
    assert "Mexican" in html
    assert "Pre-filled recipe from www.allrecipes.com" in html
    assert "Admin Review Required" in html
    assert 'name="is_web_imported" value="1"' in html


@pytest.mark.django_db
def test_recipe_import_url_view_errors(client: Client, auth_user, monkeypatch):
    """Test validation and error handling for recipe URL imports."""
    from unittest.mock import MagicMock

    import requests

    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    # 1. Empty URL
    resp1 = client.post(reverse("recipes:import_url"), {"url": ""})
    assert resp1.status_code == 302

    # 2. Page without recipe data
    mock_empty = MagicMock()
    mock_empty.text = "<html><body><h1>Just a blog post</h1><p>No food here.</p></body></html>"
    mock_empty.is_redirect = False
    mock_empty.status_code = 200
    mock_empty.raise_for_status = MagicMock()
    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: mock_empty)

    resp2 = client.post(reverse("recipes:import_url"), {"url": "https://example.com/no-recipe"})
    assert resp2.status_code == 302
    assert not Recipe.objects.filter(name="Just a blog post").exists()


@pytest.mark.django_db
def test_import_recipes_management_command(tmp_path):
    """Test the safe, idempotent import_recipes management command."""
    import yaml
    from django.core.management import call_command

    from apps.recipes.models import Ingredient, Recipe

    # Setup initial recipe
    orig = Recipe.objects.create(name="Existing Dish", description="Original description")
    orig_ing = Ingredient.objects.create(recipe=orig, name="Garlic", amount=2, amount_unit="cloves", order=0)
    orig_ing_id = orig_ing.id

    # Create YAML containing the existing dish (with new text) and a brand new dish
    yaml_content = {
        "Existing Dish": {
            "description": "Updated description",
            "ingredients": ["Garlic", "Salt"],
        },
        "Brand New Dish": {
            "description": "Delicious new creation",
            "directions": "Cook thoroughly and enjoy.",
            "ingredients": [
                {"Olive Oil": {"amount": "2 tbsp"}},
                "Onion",
            ],
        },
    }
    yaml_file = tmp_path / "test_recipes.yaml"
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_content, f)

    # 1. Dry run should not create anything
    call_command("import_recipes", file=str(yaml_file), dry_run=True)
    assert not Recipe.objects.filter(name="Brand New Dish").exists()
    assert Recipe.objects.get(name="Existing Dish").description == "Original description"
    assert Ingredient.objects.filter(id=orig_ing_id).exists()

    # 2. Real import should create only the new dish, leaving existing dish and its ingredient ID intact
    call_command("import_recipes", file=str(yaml_file))
    assert Recipe.objects.filter(name="Brand New Dish").exists()
    new_recipe = Recipe.objects.get(name="Brand New Dish")
    assert new_recipe.ingredients.count() == 2
    assert new_recipe.ingredients.filter(name="Olive Oil", amount=2, amount_unit="tbsp").exists()

    # Existing recipe was skipped by default; its ingredient ID is completely unchanged
    assert Recipe.objects.get(name="Existing Dish").description == "Original description"
    assert Ingredient.objects.filter(id=orig_ing_id).exists()

    # 3. Running with --update-existing updates description without deleting existing ingredients
    call_command("import_recipes", file=str(yaml_file), update_existing=True)
    assert Recipe.objects.get(name="Existing Dish").description == "Updated description"
    assert Ingredient.objects.filter(id=orig_ing_id).exists()


@pytest.mark.django_db
def test_recipe_search_multi_word_and_ranking(sample_recipes):
    # Create two recipes: one with "Stuffed Shells" in name, one with "stuffed" only in description
    r_name = Recipe.objects.create(
        name="Stuffed Shells",
        description="Delicious jumbo pasta filled with cheese.",
        directions="Bake until bubbly.",
        is_public=True,
        is_approved=True,
    )
    r_desc = Recipe.objects.create(
        name="Chile Rellenos",
        description="Poblano peppers stuffed with cheese.",
        directions="Fry and serve.",
        is_public=True,
        is_approved=True,
    )

    # 1. Search by exact phrase "Stuffed Shells" -> should retrieve Stuffed Shells
    res1 = list(search_recipes({"q": "Stuffed Shells"}))
    assert r_name in res1

    # 2. Search with quotes '"Stuffed shells"' -> quotes stripped, retrieves Stuffed Shells
    res2 = list(search_recipes({"q": '"Stuffed shells"'}))
    assert r_name in res2

    # 3. Search single word "shells" -> retrieves Stuffed Shells
    res3 = list(search_recipes({"q": "shells"}))
    assert r_name in res3

    # 4. Search single word "stuffed" -> retrieves both, but Stuffed Shells ranked first due to name relevance
    res4 = list(search_recipes({"q": "stuffed"}))
    assert r_name in res4
    assert r_desc in res4
    assert res4.index(r_name) < res4.index(r_desc)

    # 5. Search multi-word reversed "shells stuffed" -> matches both words
    res5 = list(search_recipes({"q": "shells stuffed"}))
    assert r_name in res5


@pytest.mark.django_db
def test_edit_recipe_preserves_approval_for_already_approved_recipes(auth_user):
    user, _ = auth_user
    # Existing approved recipe
    rec = Recipe.objects.create(
        name="Approved Garlic Bread",
        is_public=True,
        is_approved=True,
        created_by=None,
    )

    # User edits recipe
    updated = create_or_update_recipe(
        {
            "name": "Approved Garlic Bread",
            "directions": "Toast for 5 minutes with garlic butter.",
            "has_public_toggle": "1",
            "is_public": "1",
        },
        recipe_id=rec.id,
        user=user,
    )
    # Must remain public and approved!
    assert updated.is_public is True
    assert updated.is_approved is True


@pytest.mark.django_db
def test_web_imported_recipe_cannot_be_made_public_by_non_staff(auth_user):
    """Ensure web-imported recipes cannot be made public by non-staff until copyright-cleared."""
    from django.core.exceptions import ValidationError

    user, _ = auth_user
    imported = Recipe.objects.create(
        name="Scraped Chicken Soup",
        directions="Boil chicken and veggies.",
        is_web_imported=True,
        copyright_cleared=False,
        is_public=False,
        is_approved=False,
        created_by=user,
    )
    assert imported.is_locked_from_public is True
    assert imported.can_be_made_public(user) is False

    # Attempting to save as public must raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        create_or_update_recipe(
            {
                "name": "Scraped Chicken Soup",
                "directions": "Boil chicken and veggies.",
                "has_public_toggle": "1",
                "is_public": "1",
            },
            recipe_id=imported.id,
            user=user,
        )
    assert "Web-imported recipes cannot be made public" in str(exc_info.value)
    imported.refresh_from_db()
    assert imported.is_public is False


@pytest.mark.django_db
def test_web_imported_flag_inherited_on_fork_and_copy(auth_user):
    """Ensure is_web_imported flag is inherited when forking or copy-on-write modifying a recipe."""
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError

    from apps.recipes.services.recipe_service import fork_recipe

    User = get_user_model()
    user1, _ = auth_user
    user2 = User.objects.create_user(username="cook2", email="cook2@example.com")

    # User 1 has an imported recipe
    original = Recipe.objects.create(
        name="Grandma's Web Imported Lasagna",
        directions="Layer noodles and sauce.",
        is_web_imported=True,
        copyright_cleared=False,
        is_public=False,
        is_approved=False,
        created_by=user1,
    )

    # 1. User 2 forks via fork_recipe
    forked = fork_recipe(source_recipe=original, user=user2)
    assert forked.is_web_imported is True
    assert forked.copyright_cleared is False
    assert forked.is_public is False
    assert forked.is_locked_from_public is True

    # User 2 tries to make the forked recipe public -> blocked!
    with pytest.raises(ValidationError):
        create_or_update_recipe(
            {
                "name": forked.name,
                "directions": "Layer noodles and extra cheese.",
                "has_public_toggle": "1",
                "is_public": "1",
            },
            recipe_id=forked.id,
            user=user2,
        )

    # 2. User 2 triggers copy-on-write by editing User 1's recipe directly
    cow_recipe = create_or_update_recipe(
        {
            "name": "Lasagna with extra spices",
            "directions": "Layer noodles with spicy sauce.",
            "has_public_toggle": "1",
            "is_public": "0",
        },
        recipe_id=original.id,
        user=user2,
    )
    assert cow_recipe.id != original.id
    assert cow_recipe.is_web_imported is True
    assert cow_recipe.copyright_cleared is False
    assert cow_recipe.is_public is False
    assert cow_recipe.is_locked_from_public is True

    # 3. If source recipe has copyright_cleared=True, copies inherit copyright_cleared=True
    original.copyright_cleared = True
    original.save()

    cleared_fork = fork_recipe(source_recipe=original, user=user2)
    assert cleared_fork.is_web_imported is True
    assert cleared_fork.copyright_cleared is True
    assert cleared_fork.is_locked_from_public is False

    # User 2 can now make their fork public without error!
    made_public = create_or_update_recipe(
        {
            "name": cleared_fork.name,
            "directions": "Layer noodles with extra cheese.",
            "has_public_toggle": "1",
            "is_public": "1",
        },
        recipe_id=cleared_fork.id,
        user=user2,
    )
    assert made_public.is_public is True
    assert made_public.copyright_cleared is True


@pytest.mark.django_db
def test_admin_can_verify_and_publish_web_imported_recipe(auth_user):
    """Ensure administrators can verify copyright clearance and publish web-imported recipes."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    regular_user, _ = auth_user
    admin_user = User.objects.create_superuser(username="admin_chef", email="admin@example.com", password="password")

    imported = Recipe.objects.create(
        name="Imported Beef Stew",
        directions="Simmer beef slowly.",
        is_web_imported=True,
        copyright_cleared=False,
        is_public=False,
        is_approved=False,
        created_by=regular_user,
    )
    assert imported.can_be_made_public(admin_user) is True

    # Admin verifies recipe and sets it public
    verified = create_or_update_recipe(
        {
            "name": "Imported Beef Stew (Re-worded)",
            "directions": "Thoroughly re-worded directions in cook's own words.",
            "copyright_cleared": "1",
            "has_public_toggle": "1",
            "is_public": "1",
        },
        recipe_id=imported.id,
        user=admin_user,
    )
    assert verified.copyright_cleared is True
    assert verified.is_public is True
    assert verified.is_locked_from_public is False

    # Regular user owner can now update their recipe while keeping it public
    updated_by_owner = create_or_update_recipe(
        {
            "name": "Imported Beef Stew (Re-worded)",
            "directions": "Add a bay leaf and simmer.",
            "has_public_toggle": "1",
            "is_public": "1",
        },
        recipe_id=verified.id,
        user=regular_user,
    )
    assert updated_by_owner.is_public is True
    assert updated_by_owner.copyright_cleared is True


@pytest.mark.django_db
def test_recipe_admin_actions_and_batch_make_public(auth_user):
    """Test RecipeAdmin actions for verifying copyright and safety in make_public batch action."""
    from django.contrib.admin.sites import AdminSite
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    from apps.recipes.admin import RecipeAdmin

    User = get_user_model()
    admin_user = User.objects.create_superuser(username="site_admin", email="sa@example.com", password="password")
    rf = RequestFactory()
    request = rf.get("/admin/recipes/recipe/")
    request.user = admin_user
    from django.contrib.messages.storage.fallback import FallbackStorage
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))

    model_admin = RecipeAdmin(Recipe, AdminSite())

    r1 = Recipe.objects.create(name="Web Recipe A", is_web_imported=True, copyright_cleared=False, is_public=False)
    r2 = Recipe.objects.create(name="Web Recipe B", is_web_imported=True, copyright_cleared=False, is_public=False)
    r3 = Recipe.objects.create(name="Original Recipe C", is_web_imported=False, copyright_cleared=False, is_public=False)

    qs = Recipe.objects.filter(id__in=[r1.id, r2.id, r3.id])

    # Attempt batch make_public: r1 and r2 must be skipped because they are unverified web-imported!
    model_admin.make_public(request, qs)
    r1.refresh_from_db()
    r2.refresh_from_db()
    r3.refresh_from_db()
    assert r1.is_public is False
    assert r2.is_public is False
    assert r3.is_public is True

    # Admin verifies r1
    model_admin.verify_copyright(request, Recipe.objects.filter(id=r1.id))
    r1.refresh_from_db()
    assert r1.copyright_cleared is True

    # Now make_public on r1 succeeds
    model_admin.make_public(request, Recipe.objects.filter(id=r1.id))
    r1.refresh_from_db()
    assert r1.is_public is True


@pytest.mark.django_db
def test_recipe_detail_and_form_ui_for_web_imported_recipes(client: Client, auth_user):
    """Test that recipe detail and form templates display proper lock and badges for web-imported recipes."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    recipe = Recipe.objects.create(
        name="Imported Pad Thai",
        description="Classic street food noodles.",
        directions="Soak noodles, stir-fry.",
        is_web_imported=True,
        copyright_cleared=False,
        is_public=False,
        created_by=user,
    )

    # 1. Detail view shows Review Required badge and web import provenance phrasing
    resp = client.get(recipe.get_absolute_url())
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "Web-Imported (Review Required)" in html
    assert "Imported from the web by" in html
    assert "Original recipe created by" not in html
    assert "Originally created by" not in html

    # Non-web-imported recipe displays "Original recipe created by"
    orig_recipe = Recipe.objects.create(
        name="Handcrafted Stew",
        description="Made from scratch.",
        directions="Simmer slowly.",
        is_web_imported=False,
        is_public=True,
        created_by=user,
    )
    resp_orig = client.get(orig_recipe.get_absolute_url())
    html_orig = resp_orig.content.decode("utf-8")
    assert "Original recipe created by" in html_orig
    assert "Originally created by" in html_orig
    assert "Imported from the web by" not in html_orig

    # 2. Edit form disables "Make public" toggle and shows review notice
    resp_form = client.get(reverse("recipes:edit", kwargs={"recipe_id": recipe.id}))
    assert resp_form.status_code == 200
    form_html = resp_form.content.decode("utf-8")
    assert "Admin Review Required" in form_html
    assert "disabled" in form_html

    # 3. Once cleared, detail view reflects Copyright Cleared
    recipe.copyright_cleared = True
    recipe.save()
    resp_cleared = client.get(recipe.get_absolute_url())
    assert "Copyright Cleared" in resp_cleared.content.decode("utf-8")


@pytest.mark.django_db
def test_recipe_dietary_restriction_icons(client: Client, auth_user):
    """Test that meat dietary tags render meat icon, dairy tags render milk icon, and plant-based render leaf icon."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    recipe = Recipe.objects.create(
        name="Kosher Beef Brisket",
        description="Traditional slow cooked brisket.",
        directions="Sear and braise.",
        dietary_restrictions=["Kosher (Meat)", "Dairy-Free", "Gluten-Free"],
        is_public=True,
        created_by=user,
    )

    resp = client.get(recipe.get_absolute_url())
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    # Kosher (Meat) must render with meat icon 🥩 and NOT leaf 🌿
    assert "🥩 Kosher (Meat)" in html
    assert "🌿 Kosher (Meat)" not in html
    assert "🌿 Dairy-Free" in html
    assert "🌿 Gluten-Free" in html

    # Test dairy tag
    dairy_recipe = Recipe.objects.create(
        name="Cheese Blintzes",
        description="Sweet cheese stuffed crepes.",
        directions="Cook crepes, fold cheese filling.",
        dietary_restrictions=["Kosher (Dairy)", "Vegetarian"],
        is_public=True,
        created_by=user,
    )

    resp_dairy = client.get(dairy_recipe.get_absolute_url())
    assert resp_dairy.status_code == 200
    html_dairy = resp_dairy.content.decode("utf-8")

    assert "🥛 Kosher (Dairy)" in html_dairy
    assert "🌿 Kosher (Dairy)" not in html_dairy
    assert "🌿 Vegetarian" in html_dairy


@pytest.mark.django_db
def test_web_imported_recipe_cannot_be_public_without_copyright_clearance():
    """Verify that web-imported recipes cannot be made public without copyright clearance, even by staff."""
    admin = User.objects.create_user(username="superadmin", is_staff=True, is_superuser=True)
    regular_user = User.objects.create_user(username="regularuser")

    # Regular user attempting to create public web-imported recipe fails
    with pytest.raises(ValidationError) as exc:
        create_or_update_recipe(
            {
                "name": "Web Scraped Stew",
                "is_web_imported": "1",
                "is_public": "1",
                "has_public_toggle": "1",
            },
            user=regular_user,
        )
    assert "Web-imported recipes cannot be made public" in str(exc.value)

    # Superuser attempting to create public web-imported recipe without clearance fails
    with pytest.raises(ValidationError) as exc_admin:
        create_or_update_recipe(
            {
                "name": "Admin Web Scraped Stew",
                "is_web_imported": "1",
                "is_public": "1",
                "has_public_toggle": "1",
            },
            user=admin,
        )
    assert "Web-imported recipes cannot be made public" in str(exc_admin.value)

    # Superuser with copyright_cleared succeeds
    cleared_recipe = create_or_update_recipe(
        {
            "name": "Admin Web Scraped Stew (Cleared)",
            "is_web_imported": "1",
            "copyright_cleared": "1",
            "is_public": "1",
            "has_public_toggle": "1",
        },
        user=admin,
    )
    assert cleared_recipe.is_web_imported is True
    assert cleared_recipe.copyright_cleared is True
    assert cleared_recipe.is_public is True


@pytest.mark.django_db
def test_web_imported_recipe_clean_model_invariant():
    """Verify model-level full_clean invariant for web-imported public recipes."""
    recipe = Recipe(
        name="Invariant Violation Recipe",
        is_web_imported=True,
        copyright_cleared=False,
        is_public=True,
    )
    with pytest.raises(ValidationError) as exc:
        recipe.full_clean()
    assert "Web-imported recipes cannot be made public" in str(exc.value)


def test_fetch_recipe_html_handles_403_gracefully(monkeypatch):
    """Verify that fetch_recipe_html provides a descriptive error guiding user to the bookmarklet on 403."""
    from unittest.mock import MagicMock

    import requests

    from apps.recipes.services.recipe_scraper import fetch_recipe_html

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.is_redirect = False
    monkeypatch.setattr(requests.Session, "get", lambda *args, **kwargs: mock_resp)

    with pytest.raises(ValueError) as exc:
        fetch_recipe_html("https://sallysbakingaddiction.com/easy-homemade-soft-pretzels/")

    assert "HTTP 403 Forbidden: anti-bot protection" in str(exc.value)
    assert "Save Recipe" in str(exc.value)
    assert "bookmarklet" in str(exc.value)


@pytest.mark.django_db
def test_recipe_bookmarklet_import_view_authenticated(client: Client, auth_user):
    """Verify that posting URL and HTML from the bookmarklet pre-fills recipe_create form."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    url = "https://www.allrecipes.com/recipe/158968/classic-guacamole/"
    resp = client.post(
        reverse("recipes:import_bookmarklet"),
        {
            "url": url,
            "html": MOCK_RECIPE_HTML,
        },
    )
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "Classic Guacamole" in html
    assert "Authentic homemade fresh guacamole." in html
    assert "Pre-filled recipe from www.allrecipes.com via bookmarklet!" in html


@pytest.mark.django_db
def test_recipe_bookmarklet_import_view_unauthenticated(client: Client):
    """Verify that an unauthenticated request to the bookmarklet endpoint redirects to login and preserves url."""
    resp = client.get(
        reverse("recipes:import_bookmarklet") + "?url=https://example.com/recipe",
    )
    assert resp.status_code == 302
    assert reverse("core:login") in resp.url
    assert "import-bookmarklet" in resp.url
    assert "example.com" in resp.url


@pytest.mark.django_db
def test_recipe_bookmarklet_import_view_readonly_workspace(client: Client, auth_user):
    """Verify that a user with read-only workspace access receives 403 Forbidden."""
    from apps.core.models import WorkspaceMember, WorkspaceRole

    _, workspace = auth_user
    viewer = User.objects.create_user(username="viewer_user", password="testpassword123")
    WorkspaceMember.objects.create(workspace=workspace, user=viewer, role=WorkspaceRole.VIEWER)

    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    resp = client.post(
        reverse("recipes:import_bookmarklet"),
        {"url": "https://example.com/recipe"},
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_recipe_bookmarklet_import_view_get_bridge(client: Client, auth_user):
    """Verify that GET to bookmarklet endpoint renders the bridge HTML with COOP unsafe-none and postMessage/hash listeners."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    resp = client.get(reverse("recipes:import_bookmarklet") + "?url=https://www.allrecipes.com/recipe/158968/")
    assert resp.status_code == 200
    assert resp.headers.get("Cross-Origin-Opener-Policy") == "unsafe-none"
    html = resp.content.decode("utf-8")
    assert "Importing Recipe from Browser Tab..." in html
    assert "READY_FOR_RECIPE_PAYLOAD" in html
    assert "window.location.hash" in html
    assert "bridge-form" in html


@pytest.mark.django_db
def test_recipe_list_renders_bookmarklet_button(client: Client, auth_user):
    """Verify that the recipe list modal renders the one-click bookmarklet with correct JavaScript."""
    user, workspace = auth_user
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = workspace.id
    session.save()

    resp = client.get(reverse("recipes:list"))
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "+ Save Recipe" in content
    assert "One-Click Bookmarklet" in content
    assert "import-bookmarklet" in content
    assert "READY_FOR_RECIPE_PAYLOAD" in content





