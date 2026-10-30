import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from apps.core.services.workspace_service import create_workspace
from apps.mealplans.models import Meal
from apps.recipes.models import Recipe, Ingredient
from apps.mealplans.services.mealplan_service import (
    add_recipe_to_meal,
    remove_recipe_from_meal,
    delete_meal_from_plan,
)

User = get_user_model()

@pytest.fixture
def workspace_with_recipes(db):
    user = User.objects.create_user(username="testuser", password="password")
    ws = create_workspace("Test Workspace", user)
    sl = ws.get_primary_list()
    mp = ws.get_meal_plan()

    # Recipe 1: Tacos
    r1 = Recipe.objects.create(name="Tacos")
    Ingredient.objects.create(recipe=r1, name="ground beef", amount=Decimal("1.00"), amount_unit="lb")
    Ingredient.objects.create(recipe=r1, name="onion", amount=Decimal("1.00"), amount_unit="")
    Ingredient.objects.create(recipe=r1, name="garlic", amount=Decimal("2.00"), amount_unit="cloves")
    Ingredient.objects.create(recipe=r1, name="sour cream", amount=Decimal("1.00"), amount_unit="tub")

    # Recipe 2: Pasta Bolognese (shares ground beef, onion, garlic)
    r2 = Recipe.objects.create(name="Bolognese")
    Ingredient.objects.create(recipe=r2, name="ground beef", amount=Decimal("1.00"), amount_unit="lb")
    Ingredient.objects.create(recipe=r2, name="onion", amount=Decimal("1.00"), amount_unit="")
    Ingredient.objects.create(recipe=r2, name="garlic", amount=Decimal("3.00"), amount_unit="cloves")
    Ingredient.objects.create(recipe=r2, name="pasta", amount=Decimal("1.00"), amount_unit="box")

    # Recipe 3: Salad (shares sour cream, onion)
    r3 = Recipe.objects.create(name="Salad")
    Ingredient.objects.create(recipe=r3, name="lettuce", amount=Decimal("1.00"), amount_unit="head")
    Ingredient.objects.create(recipe=r3, name="onion", amount=Decimal("0.50"), amount_unit="")
    Ingredient.objects.create(recipe=r3, name="sour cream", amount=Decimal("1.00"), amount_unit="tub")

    return {
        "user": user,
        "ws": ws,
        "sl": sl,
        "mp": mp,
        "r1": r1,
        "r2": r2,
        "r3": r3,
    }

def test_add_several_dishes_then_remove_all(workspace_with_recipes):
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1, r2, r3 = data["r1"], data["r2"], data["r3"]

    m1 = Meal.objects.create(meal_plan=mp, name="Meal 1")

    # Add all 3 recipes to the meal
    add_recipe_to_meal(m1, r1, sl)
    add_recipe_to_meal(m1, r2, sl)
    add_recipe_to_meal(m1, r3, sl)

    assert sl.items.count() > 0

    # Remove recipes one by one
    remove_recipe_from_meal(m1, r1, sl)
    remove_recipe_from_meal(m1, r2, sl)
    remove_recipe_from_meal(m1, r3, sl)

    remaining = list(sl.items.all())
    for item in remaining:
        print(f"REMAINING: {item.name}, {item.amount} {item.amount_unit}, purpose: {item.purpose}")

    assert sl.items.count() == 0, f"Expected shopping list to be empty, but found {len(remaining)} items: {remaining}"


def test_same_recipe_in_two_meals_then_remove(workspace_with_recipes):
    """When the same recipe is added to multiple meals and removed, no items should be left over as one-time purchase."""
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]

    m1 = Meal.objects.create(meal_plan=mp, name="Meal 1")
    m2 = Meal.objects.create(meal_plan=mp, name="Meal 2")

    add_recipe_to_meal(m1, r1, sl)
    add_recipe_to_meal(m2, r1, sl)

    # Remove from first meal
    remove_recipe_from_meal(m1, r1, sl)

    # Verify purpose is still Tacos for remaining meal, NOT one-time purchase!
    for item in sl.items.all():
        assert "one-time purchase" not in item.purpose, f"Item {item.name} became 'one-time purchase' prematurely!"

    # Remove from second meal
    remove_recipe_from_meal(m2, r1, sl)

    remaining = list(sl.items.all())
    assert len(remaining) == 0, f"Expected 0 items, found: {remaining}"


def test_substring_recipe_names(workspace_with_recipes):
    """Recipes where one name is a substring of another should not corrupt each other's purposes or leave one-time purchases."""
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]

    r_short = Recipe.objects.create(name="Taco")
    Ingredient.objects.create(recipe=r_short, name="cheese", amount=Decimal("1.00"), amount_unit="cup")

    r_long = Recipe.objects.create(name="Taco Salad")
    Ingredient.objects.create(recipe=r_long, name="cheese", amount=Decimal("2.00"), amount_unit="cup")

    m = Meal.objects.create(meal_plan=mp, name="Meal")
    add_recipe_to_meal(m, r_short, sl)
    add_recipe_to_meal(m, r_long, sl)

    # Remove short recipe
    remove_recipe_from_meal(m, r_short, sl)

    cheese = sl.items.get(name="cheese")
    assert cheese.amount == Decimal("2.00")
    assert "one-time purchase" not in cheese.purpose
    assert "Taco Salad" in cheese.purpose

    # Remove long recipe
    remove_recipe_from_meal(m, r_long, sl)
    assert sl.items.count() == 0


def test_items_marked_got_or_have_or_dont_need_are_still_removed(workspace_with_recipes):
    """Items placed in GOT/HAVE/DONT_NEED must still be removed when the dish is removed or meal plan cleared."""
    from apps.shopping.models import ItemStatus
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]

    m = Meal.objects.create(meal_plan=mp, name="Meal")
    add_recipe_to_meal(m, r1, sl)

    # User marks items as GOT, HAVE, DONT_NEED
    items = list(sl.items.all())
    items[0].status = ItemStatus.GOT
    items[0].save()
    items[1].status = ItemStatus.HAVE
    items[1].save()
    items[2].status = ItemStatus.DONT_NEED
    items[2].save()

    # Now remove recipe
    remove_recipe_from_meal(m, r1, sl)
    remaining = list(sl.items.all())
    assert len(remaining) == 0, f"Expected 0 items, found: {remaining}"


def test_manual_item_combined_with_recipe_persists_manual_quantity(workspace_with_recipes):
    """If an item was added manually and then combined with a recipe dish, removing the recipe only removes the recipe portion."""
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]

    # Manual pre-existing item: 1 lb ground beef
    sl.items.create(
        name="ground beef",
        amount=Decimal("1.00"),
        amount_unit="lb",
        purpose="one-time purchase",
    )

    m = Meal.objects.create(meal_plan=mp, name="Meal")
    add_recipe_to_meal(m, r1, sl)

    # 1 manual + 1 from recipe = 2
    beef = sl.items.get(name="ground beef")
    assert beef.amount == Decimal("2.00")
    assert "one-time purchase" in beef.purpose
    assert "Tacos" in beef.purpose

    # Remove recipe
    remove_recipe_from_meal(m, r1, sl)

    # Only manual 1 lb ground beef remains! Other Tacos ingredients (onion, garlic, sour cream) are completely gone!
    assert sl.items.count() == 1
    remaining_beef = sl.items.first()
    assert remaining_beef.name == "ground beef"
    assert remaining_beef.amount == Decimal("1.00")
    assert remaining_beef.purpose == "one-time purchase"


def test_scale_factor_preserves_immutable_quantities(workspace_with_recipes):
    """Portion scaled recipes correctly deduct exact scaled amounts without leaving remnants."""
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]

    m = Meal.objects.create(meal_plan=mp, name="Meal")
    add_recipe_to_meal(m, r1, sl, scale_factor=Decimal("2.50"))

    beef = sl.items.get(name="ground beef")
    assert beef.amount == Decimal("2.50")

    remove_recipe_from_meal(m, r1, sl)
    assert sl.items.count() == 0


def test_preset_list_and_recipe_combined_lifecycle(workspace_with_recipes):
    """Items loaded from preset lists and recipe dishes coexist cleanly and unload cleanly."""
    from apps.shopping.services.preset_service import create_preset_list, add_preset_item, load_preset_items_to_shopping_list, unload_preset_from_shopping_list

    data = workspace_with_recipes
    ws = data["ws"]
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]

    preset = create_preset_list(ws, "Taco Party Essentials")
    add_preset_item(preset, name="sour cream", amount=Decimal("2.00"), amount_unit="tub")

    load_preset_items_to_shopping_list(preset, sl)
    assert sl.items.count() == 1
    assert sl.items.get(name="sour cream").amount == Decimal("2.00")

    # Add recipe (needs 1 tub sour cream)
    m = Meal.objects.create(meal_plan=mp, name="Meal")
    add_recipe_to_meal(m, r1, sl)

    # Combined: 2 from preset + 1 from recipe = 3
    cream = sl.items.get(name="sour cream")
    assert cream.amount == Decimal("3.00")
    assert "Preset: Taco Party Essentials" in cream.purpose
    assert "Tacos" in cream.purpose

    # Remove recipe
    remove_recipe_from_meal(m, r1, sl)

    # Preset item remains at 2 tubs
    cream.refresh_from_db()
    assert cream.amount == Decimal("2.00")
    assert cream.purpose == "Preset: Taco Party Essentials"
    # All other recipe ingredients deleted
    assert sl.items.count() == 1

    # Unload preset
    unload_preset_from_shopping_list(preset, sl)
    assert sl.items.count() == 0


def test_mark_dish_as_made_removes_shopping_list_items(workspace_with_recipes):
    """Marking a dish as made should remove its shopping list items just like removing a dish."""
    from apps.recipes.services.recipe_service import record_recipe_made

    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]
    user = data["user"]

    m = Meal.objects.create(meal_plan=mp, name="Dinner")
    add_recipe_to_meal(m, r1, sl)
    assert sl.items.count() > 0

    # Simulate what mark_dish_made view does:
    record_recipe_made(r1, user=user)
    remove_recipe_from_meal(m, r1, sl)

    assert sl.items.count() == 0
    assert r1.times_made == 1


def test_delete_meal_from_plan_removes_all_dish_sources(workspace_with_recipes):
    """Deleting a meal from the plan cleans up all ingredient sources and deletes items."""
    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1, r2 = data["r1"], data["r2"]

    m = Meal.objects.create(meal_plan=mp, name="Dinner")
    add_recipe_to_meal(m, r1, sl)
    add_recipe_to_meal(m, r2, sl)
    assert sl.items.count() > 0

    delete_meal_from_plan(m, sl)

    assert sl.items.count() == 0


def test_add_dish_multiple_times_to_same_meal_shows_twice_and_separate_scaling(workspace_with_recipes):
    """Adding a dish multiple times to the same meal creates distinct occurrences that can be scaled and removed separately."""
    from apps.mealplans.services.mealplan_service import scale_meal_dish, remove_dish_from_meal

    data = workspace_with_recipes
    sl = data["sl"]
    mp = data["mp"]
    r1 = data["r1"]  # Tacos: 1 lb ground beef, 1 onion, 2 garlic cloves, 1 tub sour cream

    m = Meal.objects.create(meal_plan=mp, name="Fiesta Night")

    # Add Tacos first time at scale 1.0
    add_recipe_to_meal(m, r1, sl, scale_factor=Decimal("1.00"))

    # Add Tacos second time at scale 2.0
    add_recipe_to_meal(m, r1, sl, scale_factor=Decimal("2.00"))

    # Assert meal shows 2 dishes
    dishes = m.dishes_list
    assert len(dishes) == 2, f"Expected 2 dishes, got {len(dishes)}"
    dish1, dish2 = dishes[0], dishes[1]
    assert dish1.id != dish2.id
    assert dish1.scale_factor == Decimal("1.00")
    assert dish2.scale_factor == Decimal("2.00")
    assert dish1.recipe == r1
    assert dish2.recipe == r1

    # Ingredients on shopping list should reflect 1 + 2 = 3x
    beef = sl.items.get(name="ground beef")
    assert beef.amount == Decimal("3.00")
    sour_cream = sl.items.get(name="sour cream")
    assert sour_cream.amount == Decimal("3.00")

    # Scale dish 1 from 1.0 to 1.5
    scale_meal_dish(dish1, Decimal("1.50"), sl)
    dish1.refresh_from_db()
    assert dish1.scale_factor == Decimal("1.50")

    # Now ingredients should reflect 1.5 + 2 = 3.5x
    beef.refresh_from_db()
    assert beef.amount == Decimal("3.50")

    # Remove dish 2 (the 2.0x occurrence)
    remove_dish_from_meal(dish2, sl)

    # Dish 1 should still be present in the meal
    remaining_dishes = m.dishes_list
    assert len(remaining_dishes) == 1
    assert remaining_dishes[0].id == dish1.id
    assert m.recipes.filter(id=r1.id).exists()

    # Shopping list should now reflect only dish 1 (1.5x)
    beef.refresh_from_db()
    assert beef.amount == Decimal("1.50")
    sour_cream.refresh_from_db()
    assert sour_cream.amount == Decimal("1.50")

    # Now remove dish 1
    remove_dish_from_meal(dish1, sl)

    # Meal is now empty and recipe is disassociated
    assert len(m.dishes_list) == 0
    assert not m.recipes.filter(id=r1.id).exists()
    assert sl.items.count() == 0


