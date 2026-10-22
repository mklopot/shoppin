"""
Service layer for Meal Plan management, recipe dish composition,
ingredient loading onto the shopping list, and cooking readiness calculation.
"""

from decimal import Decimal
from typing import Any

from django.http import HttpRequest

from apps.core.categorizer import categorizer
from apps.core.services.workspace_service import get_active_workspace
from apps.core.utils import (
    can_combine_units,
    combine_amounts_and_units,
    singularize,
)
from apps.mealplans.models import Meal, MealPlan
from apps.mealplans.services.emojifier import get_meal_emoji
from apps.recipes.models import Recipe
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.store_service import resolve_store_aisle


def get_active_meal_plan(request: HttpRequest | None = None, workspace: Any = None) -> MealPlan:
    """
    Retrieve or initialize the primary MealPlan for the active workspace.

    Args:
        request: Django HttpRequest or None.
        workspace: Optional explicit Workspace instance.

    Returns:
        The active MealPlan instance.
    """
    if not workspace:
        workspace = get_active_workspace(request)

    meal_plan = workspace.get_meal_plan()
    if not meal_plan:
        meal_plan = MealPlan.objects.create(
            name=f"{workspace.name} Meal Plan",
            workspace=workspace,
            owner=workspace.owner,
        )
    return meal_plan


def add_meal_to_plan(meal_plan: MealPlan, meal_name: str) -> Meal:
    """
    Create a new meal entry within the meal plan.

    Args:
        meal_plan: Target MealPlan.
        meal_name: Name of the meal (e.g. 'Monday Dinner', 'Taco Tuesday').

    Returns:
        The created Meal instance.
    """
    next_order = (meal_plan.meals.count() or 0) + 1
    meal = Meal.objects.create(
        meal_plan=meal_plan,
        name=meal_name.strip(),
        order=next_order,
    )
    return meal


def delete_meal_from_plan(meal: Meal, shopping_list: ShoppingList) -> None:
    """
    Delete a meal and remove all its recipe ingredients from the shopping list.

    Args:
        meal: Target Meal.
        shopping_list: Workspace active ShoppingList.
    """
    for recipe in meal.recipes.all():
        remove_recipe_from_meal(meal, recipe, shopping_list)

    meal.delete()


def add_recipe_to_meal(
    meal: Meal,
    recipe: Recipe,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
) -> list[str]:
    """
    Add a recipe dish to a meal and populate its ingredients onto the shopping list.

    Args:
        meal: Target Meal.
        recipe: Target Recipe.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for attribution / WebSocket sender client ID.

    Returns:
        List of formatted strings describing each added or combined ingredient.
    """
    meal.recipes.add(recipe)

    # Re-evaluate emoji if current meal emoji is empty
    if not meal.emoji:
        meal.emoji = get_meal_emoji(f"{meal.name} {recipe.name}")
        meal.save(update_fields=["emoji"])

    # Load ingredients into shopping list
    added_descriptions: list[str] = []

    for ingredient in recipe.ingredients.all():
        normalized_name = singularize(ingredient.name.lower())
        brand = ingredient.brand or ""
        unit = ingredient.amount_unit or ""

        # Format amount and unit for clean user-facing description
        amount_raw = f"{ingredient.amount:.2g}"
        amount_fmt = amount_raw.rstrip("0").rstrip(".") if "." in amount_raw else amount_raw
        unit_str = f" {ingredient.amount_unit}" if ingredient.amount_unit else ""

        # Check for existing NEED item on list to combine
        existing = None
        for candidate in shopping_list.items.filter(status=ItemStatus.NEED):
            if (
                singularize(candidate.name.lower()) == normalized_name
                and can_combine_units(candidate.amount_unit, unit)
                and candidate.brand.lower() == brand.lower()
            ):
                existing = candidate
                break

        if existing:
            # Combine amounts
            combined_amount, combined_unit = combine_amounts_and_units(
                existing.amount,
                existing.amount_unit,
                ingredient.amount,
                unit,
            )
            existing.amount = combined_amount
            existing.amount_unit = combined_unit
            if recipe.name not in existing.purpose:
                existing.purpose = f"{existing.purpose}, {recipe.name}" if existing.purpose else f"For {recipe.name}"
            existing.source_meal = meal
            existing.source_recipe = recipe
            # Combined with additional amount -> reset to not confirmed status
            existing.locked = False
            existing.save()
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name} (combined)")
        else:
            # Infer category
            cat = ingredient.category or categorizer.get_category(ingredient.name)

            # Resolve aisle if active store
            aisle = ""
            if shopping_list.active_store:
                aisle_info = resolve_store_aisle(shopping_list.active_store, ingredient.name)
                aisle = aisle_info.get("aisle_name", "")

            ShoppingListItem.objects.create(
                shopping_list=shopping_list,
                name=ingredient.name,
                amount=ingredient.amount,
                amount_unit=ingredient.amount_unit,
                brand=ingredient.brand,
                vendor=ingredient.vendor,
                optional=ingredient.optional,
                category=cat,
                aisle=aisle,
                purpose=f"For {recipe.name}",
                status=ItemStatus.NEED,
                source_meal=meal,
                source_recipe=recipe,
                source_ingredient=ingredient,
            )
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name}".strip())

    # Broadcast WebSocket update
    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    summary_preview = ", ".join(added_descriptions[:3])
    if len(added_descriptions) > 3:
        summary_preview += f", +{len(added_descriptions) - 3} more"

    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Added '{recipe.name}' ingredients to shopping list ({summary_preview})",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )
    return added_descriptions


def remove_recipe_from_meal(
    meal: Meal,
    recipe: Recipe,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
) -> None:
    """
    Remove a recipe dish from a meal and deduct its ingredients from the shopping list.

    Args:
        meal: Target Meal.
        recipe: Target Recipe.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for WebSocket attribution.
    """
    meal.recipes.remove(recipe)

    for ingredient in recipe.ingredients.all():
        normalized_name = singularize(ingredient.name.lower())
        items = shopping_list.items.filter(name__iexact=ingredient.name)
        if not items.exists():
            items = [
                it for it in shopping_list.items.all()
                if singularize(it.name.lower()) == normalized_name
            ]

        for item in items:
            if item.source_recipe == recipe or f"For {recipe.name}" in item.purpose or recipe.name in item.purpose:
                # Deduct amount
                try:
                    new_amount = item.amount - ingredient.amount
                except Exception:
                    new_amount = Decimal("0.00")

                if new_amount <= Decimal("0.00"):
                    item.delete()
                else:
                    item.amount = new_amount
                    # Clean up purpose string
                    purposes = [p.strip() for p in item.purpose.split(",") if p.strip() and recipe.name not in p]
                    item.purpose = ", ".join(purposes) if purposes else "one-time purchase"
                    item.save()

    # Broadcast WebSocket update
    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Removed '{recipe.name}' ingredients from shopping list",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )


def compute_cooking_status(meal_plan: MealPlan, shopping_list: ShoppingList) -> dict[str, Any]:
    """
    Compute cooking readiness status (🟢 Ready, 🟡 Missing optional) for recipes and meals.

    Matches legacy status_by_attribution logic:
    - Recipe is Ready (🟢) if none of its shopping list ingredients are NEED.
    - Recipe is Missing Optional (🟡) if only optional ingredients are NEED.
    - Meal is Ready (🟢) if all its recipes are Ready.
    - Meal is Missing Optional (🟡) if all its recipes are either Ready or Missing Optional.

    Args:
        meal_plan: Target MealPlan.
        shopping_list: Workspace active ShoppingList.

    Returns:
        Dictionary mapping:
        {
            'recipes_ready': set of recipe ids,
            'recipes_missing_optional': set of recipe ids,
            'meals_ready': set of meal ids,
            'meals_missing_optional': set of meal ids,
        }
    """
    recipes_ready = set()
    recipes_missing_optional = set()

    # Fetch all items on shopping list once for efficiency
    shopping_items = list(shopping_list.items.all())

    all_meals = list(meal_plan.meals.prefetch_related("recipes", "recipes__ingredients").all())

    for meal in all_meals:
        for recipe in meal.recipes.all():
            if recipe.id in recipes_ready or recipe.id in recipes_missing_optional:
                continue

            # Find all shopping list items attributed to this recipe
            attributed_items = [
                item for item in shopping_items
                if item.source_recipe_id == recipe.id or recipe.name.lower() in item.purpose.lower()
            ]

            if not attributed_items:
                # If no ingredients on shopping list (all checked or not added), check recipe ingredients
                recipes_ready.add(recipe.id)
                continue

            statuses = {item.status for item in attributed_items}
            statuses_ignore_optional = {
                item.status for item in attributed_items if not item.optional
            }

            if ItemStatus.NEED not in statuses:
                recipes_ready.add(recipe.id)
            elif ItemStatus.NEED not in statuses_ignore_optional:
                recipes_missing_optional.add(recipe.id)

    meals_ready = set()
    meals_missing_optional = set()

    for meal in all_meals:
        recipe_count = meal.recipes.count()
        if recipe_count == 0:
            continue

        num_ready = sum(1 for r in meal.recipes.all() if r.id in recipes_ready)
        num_missing_opt = sum(1 for r in meal.recipes.all() if r.id in recipes_missing_optional)

        if num_ready == recipe_count:
            meals_ready.add(meal.id)
        elif (num_ready + num_missing_opt) == recipe_count:
            meals_missing_optional.add(meal.id)

    return {
        "recipes_ready": recipes_ready,
        "recipes_missing_optional": recipes_missing_optional,
        "meals_ready": meals_ready,
        "meals_missing_optional": meals_missing_optional,
    }
