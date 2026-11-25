"""
Tests for per-workspace archiving of made meals, search/filter by title words,
dish name, and ingredient, sorting by rating, and loading copies into a Meal Plan.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import WorkspaceRole
from apps.core.services.workspace_service import create_workspace, share_workspace
from apps.mealplans.models import ArchivedMeal, Meal, MealDish
from apps.mealplans.services.mealplan_service import (
    add_item_to_meal,
    add_meal_to_plan,
    add_recipe_to_meal,
    get_active_meal_plan,
)
from apps.recipes.models import Ingredient, Recipe, RecipeRating

User = get_user_model()


@pytest.fixture
def archive_setup(db):
    """Provide two workspaces, users with roles, recipes with distinct ingredients, and lists."""
    owner = User.objects.create_user(username="arch_owner", first_name="Alex", password="password")
    viewer = User.objects.create_user(username="arch_viewer", first_name="Pat", password="password")
    ws1 = create_workspace("Home Kitchen", owner)
    ws2 = create_workspace("Cabin Kitchen", owner)
    share_workspace(ws1, viewer, WorkspaceRole.VIEWER)

    plan1 = get_active_meal_plan(workspace=ws1)
    plan2 = get_active_meal_plan(workspace=ws2)
    list1 = ws1.get_primary_list()
    list2 = ws2.get_primary_list()

    tacos = Recipe.objects.create(name="Fiesta Tacos", directions="Brown beef and serve.", created_by=owner)
    Ingredient.objects.create(recipe=tacos, name="Ground Beef", amount=Decimal("1.00"), amount_unit="lb")
    Ingredient.objects.create(recipe=tacos, name="Cumin", amount=Decimal("1.00"), amount_unit="tsp")

    rice = Recipe.objects.create(name="Cilantro Lime Rice", directions="Cook rice.", created_by=owner)
    Ingredient.objects.create(recipe=rice, name="Jasmine Rice", amount=Decimal("2.00"), amount_unit="cups")
    Ingredient.objects.create(recipe=rice, name="Cilantro", amount=Decimal("1.00"), amount_unit="bunch")

    pasta = Recipe.objects.create(name="Pesto Penne", directions="Boil pasta.", created_by=owner)
    Ingredient.objects.create(recipe=pasta, name="Penne Pasta", amount=Decimal("1.00"), amount_unit="box")
    Ingredient.objects.create(recipe=pasta, name="Basil Pesto", amount=Decimal("4.00"), amount_unit="oz")

    soup = Recipe.objects.create(name="Roasted Tomato Bisque", directions="Simmer tomatoes.", created_by=owner)
    Ingredient.objects.create(recipe=soup, name="Heirloom Tomato", amount=Decimal("4.00"), amount_unit="")

    for rec in (tacos, rice, pasta, soup):
        rec.shared_workspaces.add(ws1, ws2)

    return {
        "owner": owner,
        "viewer": viewer,
        "ws1": ws1,
        "ws2": ws2,
        "plan1": plan1,
        "plan2": plan2,
        "list1": list1,
        "list2": list2,
        "tacos": tacos,
        "rice": rice,
        "pasta": pasta,
        "soup": soup,
    }


def _login(client, user, ws_id: int) -> None:
    client.force_login(user)
    session = client.session
    session["active_workspace_id"] = ws_id
    session.save()


@pytest.mark.django_db
def test_mark_meal_made_archives_per_workspace_and_delete_does_not(client, archive_setup):
    """Marking a meal made archives its dishes and metadata for that workspace only."""
    owner = archive_setup["owner"]
    ws1 = archive_setup["ws1"]
    ws2 = archive_setup["ws2"]
    plan1 = archive_setup["plan1"]
    list1 = archive_setup["list1"]
    tacos = archive_setup["tacos"]
    rice = archive_setup["rice"]
    pasta = archive_setup["pasta"]

    # Planned meal marked as made -> archived
    meal = add_meal_to_plan(plan1, "Friday Fiesta Dinner")
    add_recipe_to_meal(meal, tacos, list1, scale_factor=Decimal("2.00"))
    add_recipe_to_meal(meal, rice, list1)
    add_item_to_meal(meal, "Corn Chips", list1, amount_override="2 bags")

    # Canceled meal deleted directly -> NOT archived
    canceled = add_meal_to_plan(plan1, "Canceled Lunch")
    add_recipe_to_meal(canceled, pasta, list1)

    _login(client, owner, ws1.id)
    client.post(reverse("mealplans:delete_meal", args=[canceled.id]))
    assert not ArchivedMeal.objects.filter(name="Canceled Lunch").exists()

    resp = client.post(reverse("mealplans:mark_meal_made", args=[meal.id]), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    assert not Meal.objects.filter(id=meal.id).exists()

    archived = ArchivedMeal.objects.get(workspace=ws1, name="Friday Fiesta Dinner")
    assert archived.made_by == owner
    assert archived.made_actor_display == "Alex"
    assert archived.dishes.count() == 3

    taco_snap = archived.dishes.get(dish_name="Fiesta Tacos")
    assert taco_snap.scale_factor == Decimal("2.00")
    assert "Ground Beef" in taco_snap.ingredient_names_text
    assert "Cumin" in taco_snap.ingredient_names_text

    chip_snap = archived.dishes.get(is_single_item=True)
    assert chip_snap.item_name == "Corn Chips"
    assert chip_snap.amount == Decimal("2.00")
    assert chip_snap.amount_unit == "bags"

    # Second workspace remains isolated with zero archived meals
    assert ArchivedMeal.objects.filter(workspace=ws2).count() == 0
    _login(client, owner, ws2.id)
    ws2_archive_html = client.get(reverse("mealplans:archive")).content.decode("utf-8")
    assert "Friday Fiesta Dinner" not in ws2_archive_html


@pytest.mark.django_db
def test_search_archived_meals_by_title_words_dish_ingredient_and_sort_by_rating(client, archive_setup):
    """Archive supports multi-word title search, dish/ingredient search, scopes, and rating sorting."""
    owner = archive_setup["owner"]
    ws1 = archive_setup["ws1"]
    plan1 = archive_setup["plan1"]
    list1 = archive_setup["list1"]
    tacos = archive_setup["tacos"]
    rice = archive_setup["rice"]
    pasta = archive_setup["pasta"]
    soup = archive_setup["soup"]

    # Seed recipe ratings before archiving meals (and test unrated + direct meal rating)
    RecipeRating.objects.create(recipe=tacos, user=owner, stars=5, thumbs_up=True)
    RecipeRating.objects.create(recipe=rice, user=owner, stars=3, thumbs_up=True)  # Avg for tacos+rice = 4.0
    RecipeRating.objects.create(recipe=pasta, user=owner, stars=2, thumbs_up=False)  # 2.0

    m1 = add_meal_to_plan(plan1, "Sunday Taco Feast")
    add_recipe_to_meal(m1, tacos, list1)
    add_recipe_to_meal(m1, rice, list1)

    m2 = add_meal_to_plan(plan1, "Quick Weeknight Pasta")
    add_recipe_to_meal(m2, pasta, list1)

    m3 = add_meal_to_plan(plan1, "Cozy Autumn Comfort")
    add_recipe_to_meal(m3, soup, list1)  # Unrated

    _login(client, owner, ws1.id)
    client.post(reverse("mealplans:mark_meal_made", args=[m1.id]))
    client.post(reverse("mealplans:mark_meal_made", args=[m2.id]))
    client.post(reverse("mealplans:mark_meal_made", args=[m3.id]))

    arch1 = ArchivedMeal.objects.get(workspace=ws1, name="Sunday Taco Feast")
    arch2 = ArchivedMeal.objects.get(workspace=ws1, name="Quick Weeknight Pasta")
    arch3 = ArchivedMeal.objects.get(workspace=ws1, name="Cozy Autumn Comfort")

    archive_url = reverse("mealplans:archive")

    # 1. Search by unordered words in title
    resp_title = client.get(archive_url, {"q": "sunday feast", "search_by": "title"})
    assert [m.name for m in resp_title.context["archived_meals"]] == ["Sunday Taco Feast"]

    # 2. Search by dish name
    resp_dish = client.get(archive_url, {"q": "Cilantro Lime", "search_by": "dish"})
    assert [m.name for m in resp_dish.context["archived_meals"]] == ["Sunday Taco Feast"]

    # 3. Search by ingredient (including plural matching 'tomatoes' -> 'Heirloom Tomato')
    resp_ing = client.get(archive_url, {"q": "tomatoes", "search_by": "ingredient"})
    assert [m.name for m in resp_ing.context["archived_meals"]] == ["Cozy Autumn Comfort"]

    resp_beef = client.get(archive_url, {"q": "ground beef", "search_by": "ingredient"})
    assert [m.name for m in resp_beef.context["archived_meals"]] == ["Sunday Taco Feast"]

    # Scope separation: searching ingredient 'Basil Pesto' under title-only should not match
    resp_no_title = client.get(archive_url, {"q": "basil", "search_by": "title"})
    assert resp_no_title.context["archived_meals"] == []

    # 4. Sort by rating (arch1=4.0, arch2=2.0, arch3=Unrated -> nulls last)
    resp_desc = client.get(archive_url, {"sort": "rating_desc"})
    assert [m.id for m in resp_desc.context["archived_meals"]] == [arch1.id, arch2.id, arch3.id]

    resp_asc = client.get(archive_url, {"sort": "rating_asc"})
    assert [m.id for m in resp_asc.context["archived_meals"]] == [arch2.id, arch1.id, arch3.id]

    # 5. Rate arch2 explicitly to 5 stars via endpoint -> moves to #1 on highest rated
    rate_resp = client.post(
        reverse("mealplans:rate_archived_meal", args=[arch2.id]),
        {"rating": "5", "sort": "rating_desc"},
        HTTP_HX_REQUEST="true",
    )
    assert rate_resp.status_code == 200
    assert [m.id for m in rate_resp.context["archived_meals"]] == [arch2.id, arch1.id, arch3.id]


@pytest.mark.django_db
def test_load_copy_of_archived_meal_permissions_and_shopping_list_sync(client, archive_setup):
    """Loading an archived meal copy recreates scaled dishes/items in Meal Plan and Shopping List."""
    owner = archive_setup["owner"]
    viewer = archive_setup["viewer"]
    ws1 = archive_setup["ws1"]
    ws2 = archive_setup["ws2"]
    plan1 = archive_setup["plan1"]
    list1 = archive_setup["list1"]
    tacos = archive_setup["tacos"]

    orig = add_meal_to_plan(plan1, "Taco Night")
    add_recipe_to_meal(orig, tacos, list1, scale_factor=Decimal("2.00"))
    add_item_to_meal(orig, "Tortilla Chips", list1, amount_override="3 bags")

    _login(client, owner, ws1.id)
    client.post(reverse("mealplans:mark_meal_made", args=[orig.id]))
    assert list1.items.count() == 0

    archived = ArchivedMeal.objects.get(workspace=ws1, name="Taco Night")

    # Viewer cannot load copy or delete archived meal
    _login(client, viewer, ws1.id)
    assert client.post(reverse("mealplans:load_archived_meal", args=[archived.id])).status_code == 403
    assert client.post(reverse("mealplans:delete_archived_meal", args=[archived.id])).status_code == 403

    # Cross-workspace load denied (404)
    _login(client, owner, ws2.id)
    assert client.post(reverse("mealplans:load_archived_meal", args=[archived.id])).status_code == 404

    # Owner sees "Add Meal from Archive" next to "+ Add Meal" and no bottom drawer; viewer does not
    _login(client, viewer, ws1.id)
    viewer_plan_html = client.get(reverse("mealplans:detail")).content.decode("utf-8")
    assert 'id="open-archive-modal-btn"' not in viewer_plan_html
    assert 'id="archived-meals-details"' not in viewer_plan_html

    _login(client, owner, ws1.id)
    owner_plan_html = client.get(reverse("mealplans:detail")).content.decode("utf-8")
    assert 'id="open-archive-modal-btn"' in owner_plan_html
    assert "Add Meal from Archive" in owner_plan_html
    assert 'id="archived-meals-details"' not in owner_plan_html

    # Archive modal partial renders cleanly with search/sort browser and modal-close hook
    modal_resp = client.get(
        reverse("mealplans:archive"),
        {"embed": "1", "modal": "1"},
        HTTP_HX_REQUEST="true",
    )
    assert modal_resp.status_code == 200
    modal_html = modal_resp.content.decode("utf-8")
    assert 'id="archive-modal-title"' in modal_html
    assert 'id="archived-meals-filter-form"' in modal_html
    assert 'hx-target="#mealplan-content"' in modal_html
    assert "modal-placeholder" in modal_html

    # Lazy-loaded embedded browser partial renders cleanly with embed_in_mealplan flag
    panel_resp = client.get(
        reverse("mealplans:archive"),
        {"embed": "1", "panel": "1"},
        HTTP_HX_REQUEST="true",
    )
    assert panel_resp.status_code == 200
    panel_html = panel_resp.content.decode("utf-8")
    assert 'id="archived-meals-filter-form"' in panel_html
    assert 'hx-target="#mealplan-content"' in panel_html

    # Owner in ws1 loads copy via embedded mealplan HTMX target -> populates Meal & ShoppingList
    load_resp = client.post(
        reverse("mealplans:load_archived_meal", args=[archived.id]),
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="mealplan-content",
    )
    assert load_resp.status_code == 200
    html = load_resp.content.decode("utf-8")
    assert "Taco Night" in html
    assert "Loaded copy of" in html

    loaded_meal = Meal.objects.get(meal_plan=plan1, name="Taco Night")
    taco_dish = MealDish.objects.get(meal=loaded_meal, recipe=tacos)
    assert taco_dish.scale_factor == Decimal("2.00")
    assert taco_dish.is_made is False

    # Shopping list populated with scaled ingredient (2 lb Ground Beef) + single item (3 bags Tortilla Chips)
    beef_item = list1.items.get(name="Ground Beef")
    assert beef_item.amount == Decimal("2.00")
    assert beef_item.amount_unit == "lb"
    chips_item = list1.items.get(name="Tortilla Chips")
    assert chips_item.amount == Decimal("3.00")
    assert chips_item.amount_unit == "bags"

    # Original archive remains intact after loading copy
    assert ArchivedMeal.objects.filter(id=archived.id).exists()

    # Delete archived meal works for owner
    del_resp = client.post(
        reverse("mealplans:delete_archived_meal", args=[archived.id]),
        HTTP_HX_REQUEST="true",
    )
    assert del_resp.status_code == 200
    assert not ArchivedMeal.objects.filter(id=archived.id).exists()
