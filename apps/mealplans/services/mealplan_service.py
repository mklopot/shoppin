"""
Service layer for Meal Plan management, recipe dish composition,
ingredient loading onto the shopping list, and cooking readiness calculation.
"""

from decimal import Decimal
from typing import Any

from django.db import models
from django.http import HttpRequest

from apps.core.categorizer import categorizer
from apps.core.services.workspace_service import get_active_workspace
from apps.core.utils import (
    can_combine_units,
    clean_purpose,
    combine_amounts_and_units,
    singularize,
)
from apps.mealplans.models import Meal, MealDish, MealPlan
from apps.mealplans.services.emojifier import get_meal_emoji
from apps.recipes.models import Recipe
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, ShoppingListItemSource
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.store_service import resolve_store_aisle, warm_store_aisles_async


def get_active_meal_plan(request: HttpRequest | None = None, workspace: Any = None) -> MealPlan | None:
    """
    Retrieve or initialize the primary MealPlan for the active workspace.

    Args:
        request: Django HttpRequest or None.
        workspace: Optional explicit Workspace instance.

    Returns:
        The active MealPlan instance, or None if unauthenticated/no workspace.
    """
    if not workspace:
        workspace = get_active_workspace(request)

    if not workspace:
        return None

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


def update_meal_name(meal: Meal, new_name: str) -> Meal:
    """
    Update a meal's name and recompute its culinary emoji.
    """
    cleaned_name = new_name.strip()
    if cleaned_name:
        meal.name = cleaned_name
        meal.emoji = get_meal_emoji(cleaned_name)
        meal.save(update_fields=["name", "emoji"])
    return meal


def delete_meal_from_plan(
    meal: Meal,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
) -> None:
    """
    Delete a meal and remove all its recipe ingredients from the shopping list.

    Args:
        meal: Target Meal.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for attribution / WebSocket sender client ID.
    """
    if not shopping_list:
        shopping_list = meal.meal_plan.workspace.get_primary_list() if (meal.meal_plan and meal.meal_plan.workspace) else None

    # Remove each individual dish occurrence
    for dish in list(meal.dishes.select_related("recipe").all()):
        remove_dish_from_meal(dish, shopping_list, request)

    # Fallback for any legacy recipes not linked via MealDish
    for recipe in list(meal.recipes.all()):
        remove_recipe_from_meal(meal, recipe, shopping_list, request)

    # Clean up any residual sources tied to this meal and recalculate items
    if shopping_list:
        meal_sources = ShoppingListItemSource.objects.filter(meal=meal, item__shopping_list=shopping_list)
        affected_item_ids = list(meal_sources.values_list("item_id", flat=True).distinct())
        meal_sources.delete()
        for item_id in affected_item_ids:
            item = ShoppingListItem.objects.filter(id=item_id).first()
            if item:
                item.recalculate_from_attributions()

    meal.delete()


def add_recipe_to_meal(
    meal: Meal,
    recipe: Recipe,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
    scale_factor: Decimal | float | str = Decimal("1.00"),
) -> list[str]:
    """
    Add a recipe dish to a meal and populate its ingredients onto the shopping list,
    optionally scaled up or down by a given factor.

    Args:
        meal: Target Meal.
        recipe: Target Recipe.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for attribution / WebSocket sender client ID.
        scale_factor: Portion scaling factor (e.g. 0.5, 1.0, 2.0).

    Returns:
        List of formatted strings describing each added or combined ingredient.
    """
    try:
        factor = Decimal(str(scale_factor))
        if factor <= Decimal("0"):
            factor = Decimal("1.00")
    except Exception:
        factor = Decimal("1.00")

    meal.recipes.add(recipe)
    max_order = meal.dishes.aggregate(models.Max("order"))["order__max"]
    next_order = (max_order + 1) if max_order is not None else 0
    dish = MealDish.objects.create(
        meal=meal,
        recipe=recipe,
        scale_factor=factor,
        order=next_order,
    )

    # Re-evaluate emoji if current meal emoji is empty
    if not meal.emoji:
        meal.emoji = get_meal_emoji(f"{meal.name} {recipe.name}")
        meal.save(update_fields=["emoji"])

    # Load ingredients into shopping list
    added_descriptions: list[str] = []

    recipe_purpose_name = clean_purpose(recipe.name)

    for ingredient in recipe.ingredients.all():
        normalized_name = singularize(ingredient.name.lower())
        brand = ingredient.brand or ""
        unit = ingredient.amount_unit or ""

        # Calculate scaled amount
        scaled_amount = (ingredient.amount * factor).quantize(Decimal("0.01"))

        # Format amount and unit for clean user-facing description
        amount_raw = f"{scaled_amount.normalize():f}"
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
            target_item = existing
            target_item.locked = False
            # If the existing item had an amount but no attributions yet (e.g. pre-existing manual addition),
            # preserve its initial quantity as an authentic manual attribution so it is never lost when recipes change.
            if not target_item.attributions.exists() and target_item.amount > Decimal("0.00"):
                ShoppingListItemSource.objects.create(
                    item=target_item,
                    is_one_time=True,
                    amount=target_item.amount,
                    amount_unit=target_item.amount_unit,
                    purpose=clean_purpose(target_item.purpose) or "one-time purchase",
                )
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name} (combined)")
        else:
            # Infer category
            cat = ingredient.category or categorizer.get_category(ingredient.name)

            # Resolve aisle if active store
            aisle = ""
            if shopping_list.active_store:
                aisle_info = resolve_store_aisle(shopping_list.active_store, ingredient.name, db_only=True)
                aisle = aisle_info.get("aisle_name", "") if aisle_info else ""

            target_item = ShoppingListItem.objects.create(
                shopping_list=shopping_list,
                name=ingredient.name,
                amount=Decimal("0.00"),
                amount_unit=ingredient.amount_unit,
                brand=ingredient.brand,
                vendor=ingredient.vendor,
                optional=ingredient.optional,
                category=cat,
                aisle=aisle,
                purpose="",
                status=ItemStatus.NEED,
                source_meal=meal,
                source_recipe=recipe,
                source_ingredient=ingredient,
            )
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name}".strip())

        # Create or update the immutable attribution source
        ShoppingListItemSource.objects.create(
            item=target_item,
            meal=meal,
            meal_dish=dish,
            recipe=recipe,
            ingredient=ingredient,
            amount=scaled_amount,
            amount_unit=ingredient.amount_unit,
            purpose=recipe_purpose_name,
        )
        target_item.recalculate_from_attributions()

    # Warm missing aisles in background so user request returns immediately
    if shopping_list.active_store:
        warm_store_aisles_async(shopping_list)

    # Broadcast WebSocket update
    actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    summary_preview = ", ".join(added_descriptions[:3])
    if len(added_descriptions) > 3:
        summary_preview += f", +{len(added_descriptions) - 3} more"

    scale_tag = f" ({factor.normalize():f}x)" if factor != Decimal("1.00") else ""
    broadcast_messages = [f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name}"]
    if len(added_descriptions) <= 6:
        for desc in added_descriptions:
            broadcast_messages.append(f"🛒 Added {desc} to shopping list")
    else:
        for desc in added_descriptions[:5]:
            broadcast_messages.append(f"🛒 Added {desc} to shopping list")
        remaining = len(added_descriptions) - 5
        broadcast_messages.append(f"🛒 ...and {remaining} more ingredients added to shopping list")

    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Added '{recipe.name}'{scale_tag} ingredients to shopping list ({summary_preview})",
        toast_messages=broadcast_messages,
        actor_name=actor_name,
        sender_client_id=sender_id,
    )
    return added_descriptions


def remove_dish_from_meal(
    dish: MealDish,
    shopping_list: ShoppingList | None = None,
    request: HttpRequest | None = None,
) -> None:
    """
    Remove an individual MealDish occurrence from a meal and deduct its contributed ingredients.

    Args:
        dish: Target MealDish instance.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for WebSocket attribution.
    """
    meal = dish.meal
    recipe = dish.recipe
    factor = dish.scale_factor or Decimal("1.00")

    if not shopping_list:
        shopping_list = meal.meal_plan.workspace.get_primary_list() if (meal.meal_plan and meal.meal_plan.workspace) else None

    # 1. Query and remove immutable source attributions for this dish occurrence
    if shopping_list:
        sources_qs = ShoppingListItemSource.objects.filter(item__shopping_list=shopping_list)
        dish_sources = sources_qs.filter(meal_dish=dish)
        affected_item_ids = list(dish_sources.values_list("item_id", flat=True).distinct())
        dish_sources.delete()

        for item_id in affected_item_ids:
            item = ShoppingListItem.objects.filter(id=item_id).first()
            if item:
                item.recalculate_from_attributions()

        # 2. Backward compatibility fallback for legacy items not tracked by ShoppingListItemSource
        if not affected_item_ids:
            recipe_purpose_name = clean_purpose(recipe.name)
            for ingredient in recipe.ingredients.all():
                scaled_amount = (ingredient.amount * factor).quantize(Decimal("0.01"))
                normalized_name = singularize(ingredient.name.lower())
                items = shopping_list.items.filter(name__iexact=ingredient.name)
                if not items.exists():
                    items = [
                        it for it in shopping_list.items.all()
                        if singularize(it.name.lower()) == normalized_name
                    ]

                for item in items:
                    if item.attributions.exists():
                        continue
                    if item.source_recipe == recipe or f"For {recipe.name}" in item.purpose or recipe_purpose_name in item.purpose or recipe.name in item.purpose:
                        try:
                            new_amount = item.amount - scaled_amount
                        except Exception:
                            new_amount = Decimal("0.00")

                        if new_amount <= Decimal("0.00"):
                            item.delete()
                        else:
                            item.amount = new_amount
                            clean_existing = clean_purpose(item.purpose)
                            purposes = [p.strip() for p in clean_existing.split(",") if p.strip() and recipe_purpose_name not in p and recipe.name not in p]
                            if purposes:
                                item.purpose = ", ".join(purposes)
                                item.save()
                            else:
                                item.delete()

    # 3. Delete the MealDish instance
    dish_id = dish.id
    dish.delete()

    # 4. Only disassociate recipe from meal M2M if no other MealDish for this recipe remains
    if not meal.dishes.filter(recipe=recipe).exists():
        meal.recipes.remove(recipe)

    # Broadcast WebSocket update
    actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    if shopping_list:
        broadcast_shopping_list_update(
            shopping_list=shopping_list,
            toast_message=f"Removed '{recipe.name}' from {meal.name}",
            actor_name=actor_name,
            sender_client_id=sender_id,
        )


def remove_recipe_from_meal(
    meal: Meal,
    recipe: Recipe,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
    dish: MealDish | None = None,
) -> None:
    """
    Remove a recipe dish from a meal and deduct its scaled ingredients from the shopping list.
    Supports targeting a specific MealDish instance, or defaults to the last planned occurrence.

    Args:
        meal: Target Meal.
        recipe: Target Recipe.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for WebSocket attribution.
        dish: Optional specific MealDish to remove.
    """
    if dish is None:
        dish = meal.dishes.filter(recipe=recipe).last()

    if dish:
        remove_dish_from_meal(dish, shopping_list, request)
        return

    # Fallback if no MealDish instance exists (e.g. legacy data)
    sources_qs = ShoppingListItemSource.objects.filter(item__shopping_list=shopping_list)
    dish_sources = sources_qs.filter(meal=meal, recipe=recipe)
    affected_item_ids = list(dish_sources.values_list("item_id", flat=True).distinct())
    dish_sources.delete()

    for item_id in affected_item_ids:
        item = ShoppingListItem.objects.filter(id=item_id).first()
        if item:
            item.recalculate_from_attributions()

    meal.recipes.remove(recipe)

    actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Removed '{recipe.name}' from {meal.name}",
        actor_name=actor_name,
        sender_client_id=sender_id,
    )


def scale_meal_dish(
    dish: MealDish,
    new_scale: Decimal | float | str,
    shopping_list: ShoppingList | None = None,
    request: HttpRequest | None = None,
) -> None:
    """
    Scale an existing planned dish to a new portion multiplier,
    updating its ShoppingListItemSource attributions and recalculating affected shopping list items.
    """
    try:
        factor = Decimal(str(new_scale)).quantize(Decimal("0.01"))
        if factor <= Decimal("0"):
            factor = Decimal("1.00")
    except Exception:
        factor = Decimal("1.00")

    if factor == dish.scale_factor:
        return

    dish.scale_factor = factor
    dish.save(update_fields=["scale_factor"])

    if not shopping_list:
        shopping_list = dish.meal.meal_plan.workspace.get_primary_list() if (dish.meal.meal_plan and dish.meal.meal_plan.workspace) else None

    if shopping_list:
        recipe_purpose_name = clean_purpose(dish.recipe.name)
        affected_items = set()
        for ingredient in dish.recipe.ingredients.all():
            scaled_amount = (ingredient.amount * factor).quantize(Decimal("0.01"))
            source = ShoppingListItemSource.objects.filter(meal_dish=dish, ingredient=ingredient).first()
            if source:
                source.amount = scaled_amount
                source.save(update_fields=["amount"])
                affected_items.add(source.item)
            else:
                # If source didn't exist yet, link to or create shopping list item
                item = shopping_list.items.filter(name__iexact=ingredient.name).first()
                if not item:
                    item = ShoppingListItem.objects.create(
                        shopping_list=shopping_list,
                        name=ingredient.name,
                        amount=scaled_amount,
                        amount_unit=ingredient.amount_unit,
                        purpose=recipe_purpose_name,
                        category=ingredient.category or "Produce",
                        status=ItemStatus.NEED,
                    )
                ShoppingListItemSource.objects.create(
                    item=item,
                    meal=dish.meal,
                    meal_dish=dish,
                    recipe=dish.recipe,
                    ingredient=ingredient,
                    amount=scaled_amount,
                    amount_unit=ingredient.amount_unit,
                    purpose=recipe_purpose_name,
                )
                affected_items.add(item)

        for item in affected_items:
            item.recalculate_from_attributions()

        actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
        sender_id = request.headers.get("X-Client-Id") if request else ""
        broadcast_shopping_list_update(
            shopping_list=shopping_list,
            toast_message=f"Scaled '{dish.recipe.name}' to {factor.normalize():f}x",
            actor_name=actor_name,
            sender_client_id=sender_id,
        )


def broadcast_mealplan_update(
    request: HttpRequest | None = None,
    toast_message: str | None = None,
    toast_messages: list[str] | None = None,
    shopping_list: ShoppingList | None = None,
    workspace: Any = None,
) -> None:
    """
    Broadcast real-time meal plan updates across all open tabs and collaborators via WebSockets.
    """
    actor_name = ""
    if request and getattr(request, "user", None) and request.user.is_authenticated:
        actor_name = (request.user.first_name or "").strip() or request.user.username
    if not actor_name:
        actor_name = "Someone"

    sender_id = ""
    if request:
        sender_id = request.headers.get("X-Client-Id") or request.META.get("HTTP_X_CLIENT_ID") or ""

    if not shopping_list:
        if not workspace and request:
            workspace = get_active_workspace(request)
        if workspace:
            shopping_list = workspace.get_primary_list()

    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=toast_message,
        toast_messages=toast_messages,
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
