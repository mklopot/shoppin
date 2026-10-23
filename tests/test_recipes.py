"""
Unit and integration tests for culinary recipes:
models, search service, ratings, and views.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.core.models import Workspace
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
def auth_user(db):
    user = User.objects.create_user(
        username="chef_tester",
        email="chef@example.com",
        password="testpassword123",
    )
    workspace = Workspace.objects.create(name="Chef Test Workspace", owner=user)
    return user, workspace


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
    assert recipe.primary_photo_url == recipe.photo_file.url

    # 2. Clear photo on edit
    clear_data = {
        "name": "Homemade Pizza",
        "clear_photo": "1",
    }
    updated = create_or_update_recipe(clear_data, recipe_id=recipe.id, user=user)
    assert bool(updated.photo_file) is False
    assert updated.primary_photo_url == ""


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
    assert "Classic Tacos" in resp.content.decode("utf-8")
    assert "Vegetarian Lasagna" in resp.content.decode("utf-8")

    # List view HTMX filter GET
    resp_htmx = client.get(
        reverse("recipes:list") + "?q=lasagna",
        HTTP_HX_REQUEST="true",
    )
    assert resp_htmx.status_code == 200
    html = resp_htmx.content.decode("utf-8")
    assert "Vegetarian Lasagna" in html
    assert "Classic Tacos" not in html

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
