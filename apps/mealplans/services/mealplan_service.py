"""
Service layer for Meal Plan management, recipe dish composition,
ingredient loading onto the shopping list, and cooking readiness calculation.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest

from apps.core.categorizer import categorizer
from apps.core.services.workspace_service import get_active_workspace
from apps.core.utils import (
    can_combine_units,
    clean_purpose,
    parse_amount_and_unit,
    parse_ingredient_line,
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
    Update a meal's name, recompute its culinary emoji, and update the purpose
    of any single-item shopping list attributions bound to this meal.
    """
    cleaned_name = new_name.strip()
    if cleaned_name:
        meal.name = cleaned_name
        meal.emoji = get_meal_emoji(cleaned_name)
        meal.save(update_fields=["name", "emoji"])

        meal_purpose = clean_purpose(cleaned_name)
        single_item_sources = ShoppingListItemSource.objects.filter(meal=meal, recipe__isnull=True)
        affected_item_ids = list(single_item_sources.values_list("item_id", flat=True).distinct())
        if affected_item_ids:
            single_item_sources.update(purpose=meal_purpose)
            for item_id in affected_item_ids:
                item = ShoppingListItem.objects.filter(id=item_id).first()
                if item:
                    item.recalculate_from_attributions()
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
    enforce_workspace: bool = True,
) -> list[str]:
    """
    Add a recipe dish to a meal and populate its ingredients onto the shopping list,
    optionally scaled up or down by a given factor.
    Enforces that the recipe must be associated with the meal plan's workspace.

    Args:
        meal: Target Meal.
        recipe: Target Recipe.
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for attribution / WebSocket sender client ID.
        scale_factor: Portion scaling factor (e.g. 0.5, 1.0, 2.0).
        enforce_workspace: If True, validates recipe workspace association.

    Returns:
        List of formatted strings describing each added or combined ingredient.
    """
    workspace = meal.meal_plan.workspace if meal.meal_plan else None
    if enforce_workspace and workspace:
        if not recipe.shared_workspaces.filter(id=workspace.id).exists():
            user = getattr(request, "user", None)
            # Public recipes and recipes created by workspace members can be added to the workspace meal plan
            if recipe.is_public:
                recipe.shared_workspaces.add(workspace)
            elif recipe.created_by and workspace.can_read(recipe.created_by):
                recipe.shared_workspaces.add(workspace)
            elif not recipe.shared_workspaces.exists() and (user is None or workspace.can_write(user)):
                recipe.shared_workspaces.add(workspace)
            else:
                raise ValidationError(
                    f"Recipe '{recipe.name}' must be associated with or copied into workspace '{workspace.name}' before adding to its meal plan."
                )

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


def add_item_to_meal(
    meal: Meal,
    raw_item_input: str,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
    amount_override: Decimal | float | str | None = None,
    unit_override: str | None = None,
    scale_factor: Decimal | float | str = Decimal("1.00"),
) -> tuple[MealDish, ShoppingListItem]:
    """
    Add a single ingredient or shopping list item directly to a meal in place of a recipe dish,
    and populate it onto the shopping list with the meal's name as its purpose.

    Args:
        meal: Target Meal.
        raw_item_input: Item name or free-form quantity + item string (e.g. 'Rotisserie Chicken', '2 lbs Watermelon').
        shopping_list: Workspace active ShoppingList.
        request: Optional HttpRequest for attribution / WebSocket sender client ID.
        amount_override: Optional explicit quantity / unit string from a dedicated quantity input.
        unit_override: Optional explicit unit string.
        scale_factor: Portion scaling factor (default 1.00).

    Returns:
        Tuple of (created MealDish, created or updated ShoppingListItem).
    """
    raw_clean = (raw_item_input or "").strip()
    if not raw_clean:
        raise ValidationError("Item name is required.")

    parsed_name, line_amt, line_unit = parse_ingredient_line(raw_clean)
    raw_amt_str = str(amount_override).strip() if amount_override is not None else ""

    if raw_amt_str and raw_amt_str not in ("1", "1.0", "1.00"):
        override_amt, override_unit = parse_amount_and_unit(raw_amt_str)
        clean_name = raw_clean
        base_amount = override_amt
        unit_val = (unit_override or override_unit or "").strip()
    elif unit_override and unit_override.strip():
        override_amt, _ = parse_amount_and_unit(raw_amt_str or "1")
        clean_name = raw_clean
        base_amount = override_amt
        unit_val = unit_override.strip()
    else:
        clean_name = parsed_name or raw_clean
        base_amount = line_amt
        unit_val = line_unit

    try:
        factor = Decimal(str(scale_factor)).quantize(Decimal("0.01"))
        if factor <= Decimal("0"):
            factor = Decimal("1.00")
    except Exception:
        factor = Decimal("1.00")

    max_order = meal.dishes.aggregate(models.Max("order"))["order__max"]
    next_order = (max_order + 1) if max_order is not None else 0
    dish = MealDish.objects.create(
        meal=meal,
        recipe=None,
        item_name=clean_name,
        amount=base_amount,
        amount_unit=unit_val,
        scale_factor=factor,
        order=next_order,
    )

    if not meal.emoji:
        meal.emoji = get_meal_emoji(f"{meal.name} {clean_name}")
        meal.save(update_fields=["emoji"])

    meal_purpose_name = clean_purpose(meal.name)
    scaled_amount = (base_amount * factor).quantize(Decimal("0.01"))
    normalized_name = singularize(clean_name.lower())

    amount_raw = f"{scaled_amount.normalize():f}"
    amount_fmt = amount_raw.rstrip("0").rstrip(".") if "." in amount_raw else amount_raw
    unit_str = f" {unit_val}" if unit_val else ""

    existing = None
    for candidate in shopping_list.items.filter(status=ItemStatus.NEED):
        if (
            singularize(candidate.name.lower()) == normalized_name
            and can_combine_units(candidate.amount_unit, unit_val)
            and not candidate.brand
        ):
            existing = candidate
            break

    if existing:
        target_item = existing
        target_item.locked = False
        if not target_item.attributions.exists() and target_item.amount > Decimal("0.00"):
            ShoppingListItemSource.objects.create(
                item=target_item,
                is_one_time=True,
                amount=target_item.amount,
                amount_unit=target_item.amount_unit,
                purpose=clean_purpose(target_item.purpose) or "one-time purchase",
            )
        desc = f"{amount_fmt}{unit_str} {clean_name} (combined)"
    else:
        cat = categorizer.get_category(clean_name)
        aisle = ""
        if shopping_list.active_store:
            aisle_info = resolve_store_aisle(shopping_list.active_store, clean_name, db_only=True)
            aisle = aisle_info.get("aisle_name", "") if aisle_info else ""

        target_item = ShoppingListItem.objects.create(
            shopping_list=shopping_list,
            name=clean_name,
            amount=Decimal("0.00"),
            amount_unit=unit_val,
            category=cat,
            aisle=aisle,
            purpose=meal_purpose_name,
            status=ItemStatus.NEED,
            source_meal=meal,
        )
        desc = f"{amount_fmt}{unit_str} {clean_name}".strip()

    ShoppingListItemSource.objects.create(
        item=target_item,
        meal=meal,
        meal_dish=dish,
        recipe=None,
        ingredient=None,
        amount=scaled_amount,
        amount_unit=unit_val,
        purpose=meal_purpose_name,
    )
    target_item.recalculate_from_attributions()

    if shopping_list.active_store:
        warm_store_aisles_async(shopping_list)

    actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    scale_tag = f" ({factor.normalize():f}x)" if factor != Decimal("1.00") else ""
    broadcast_messages = [
        f"🛒 Added single item '{clean_name}'{scale_tag} to {meal.name}",
        f"🛒 Added {desc} to shopping list (for {meal.name})",
    ]
    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Added '{clean_name}' to {meal.name} and shopping list",
        toast_messages=broadcast_messages,
        actor_name=actor_name,
        sender_client_id=sender_id,
    )
    return dish, target_item


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
    dish_name = dish.display_name
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
        if not affected_item_ids and recipe:
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
    dish.delete()

    # 4. Only disassociate recipe from meal M2M if no other MealDish for this recipe remains
    if recipe and not meal.dishes.filter(recipe=recipe).exists():
        meal.recipes.remove(recipe)

    # Broadcast WebSocket update
    actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    if shopping_list:
        broadcast_shopping_list_update(
            shopping_list=shopping_list,
            toast_message=f"Removed '{dish_name}' from {meal.name}",
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
        affected_items = set()
        if dish.recipe:
            recipe_purpose_name = clean_purpose(dish.recipe.name)
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
        else:
            meal_purpose_name = clean_purpose(dish.meal.name)
            scaled_amount = (dish.amount * factor).quantize(Decimal("0.01"))
            source = ShoppingListItemSource.objects.filter(meal_dish=dish).first()
            if source:
                source.amount = scaled_amount
                source.save(update_fields=["amount"])
                affected_items.add(source.item)
            else:
                item = shopping_list.items.filter(name__iexact=dish.item_name).first()
                if not item:
                    item = ShoppingListItem.objects.create(
                        shopping_list=shopping_list,
                        name=dish.item_name,
                        amount=scaled_amount,
                        amount_unit=dish.amount_unit,
                        purpose=meal_purpose_name,
                        category=categorizer.get_category(dish.item_name),
                        status=ItemStatus.NEED,
                        source_meal=dish.meal,
                    )
                ShoppingListItemSource.objects.create(
                    item=item,
                    meal=dish.meal,
                    meal_dish=dish,
                    recipe=None,
                    ingredient=None,
                    amount=scaled_amount,
                    amount_unit=dish.amount_unit,
                    purpose=meal_purpose_name,
                )
                affected_items.add(item)

        for item in affected_items:
            item.recalculate_from_attributions()

        actor_name = (request.user.first_name or "").strip() or request.user.username if (request and request.user.is_authenticated) else "unknown"
        sender_id = request.headers.get("X-Client-Id") if request else ""
        broadcast_shopping_list_update(
            shopping_list=shopping_list,
            toast_message=f"Scaled '{dish.display_name}' to {factor.normalize():f}x",
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


def get_recipe_ingredients_status(
    recipe: Recipe,
    shopping_list: ShoppingList | None,
    meal: Meal | None = None,
    meal_dish: MealDish | None = None,
) -> list[dict[str, Any]]:
    """
    Resolve each ingredient of a recipe to its corresponding item and workflow status
    on the active shopping list.

    Status resolution hierarchy:
    1. Direct ShoppingListItemSource attribution (matching recipe and ingredient, optionally meal/dish).
    2. Direct ShoppingListItem source link (source_recipe_id and source_ingredient_id).
    3. Recipe-scoped name match (ShoppingListItemSource matching recipe and normalized ingredient name).
    4. ShoppingList-wide normalized name match (singularized lowercase).

    Returns:
        List of ingredient status dictionaries with normalized status codes:
        - "got": In Cart / Purchased (ItemStatus.GOT)
        - "have": Already Have / In Pantry (ItemStatus.HAVE)
        - "skipped": Skipped / Don't Need Today (ItemStatus.DONT_NEED)
        - "need": Active item to buy (ItemStatus.NEED)
        - "missing": Ingredient not found on shopping list
    """
    if not shopping_list:
        return [
            {
                "ingredient": ing,
                "item": None,
                "on_list": False,
                "status": None,
                "status_code": "missing",
                "status_display": "Missing",
                "is_ready": False,
                "is_available": False,
                "is_skipped": False,
                "is_need": False,
                "is_missing": True,
                "is_optional": bool(ing.optional),
            }
            for ing in recipe.ingredients.all()
        ]

    # Pre-fetch shopping items and attributions once for efficiency
    shopping_items = list(shopping_list.items.prefetch_related("attributions").all())

    # Build resolution lookup tables
    source_by_ing_id: dict[int, ShoppingListItem] = {}
    source_by_recipe_and_norm_name: dict[str, ShoppingListItem] = {}

    for item in shopping_items:
        for attr in item.attributions.all():
            if attr.recipe_id == recipe.id:
                if attr.ingredient_id:
                    # Prefer exact dish occurrence if meal_dish specified
                    if meal_dish and attr.meal_dish_id == meal_dish.id:
                        source_by_ing_id[attr.ingredient_id] = item
                    elif attr.ingredient_id not in source_by_ing_id:
                        source_by_ing_id[attr.ingredient_id] = item

                norm_attr_purpose = singularize(clean_purpose(attr.purpose).lower())
                norm_item_name = singularize(item.name.strip().lower())
                source_by_recipe_and_norm_name.setdefault(norm_attr_purpose, item)
                source_by_recipe_and_norm_name.setdefault(norm_item_name, item)

        if item.source_recipe_id == recipe.id:
            if item.source_ingredient_id and item.source_ingredient_id not in source_by_ing_id:
                source_by_ing_id[item.source_ingredient_id] = item
            source_by_recipe_and_norm_name.setdefault(singularize(item.name.strip().lower()), item)

    exact_name_map = {item.name.strip().lower(): item for item in shopping_items}
    singular_name_map = {singularize(item.name.strip().lower()): item for item in shopping_items}

    ingredients_with_status = []
    for ing in recipe.ingredients.all():
        raw_name = ing.name.strip().lower()
        norm_name = singularize(raw_name)

        item = (
            source_by_ing_id.get(ing.id)
            or source_by_recipe_and_norm_name.get(norm_name)
            or exact_name_map.get(raw_name)
            or singular_name_map.get(norm_name)
        )

        if item:
            status = item.status
            if status == ItemStatus.GOT:
                status_code = "got"
                status_display = "Got"
            elif status == ItemStatus.HAVE:
                status_code = "have"
                status_display = "Have"
            elif status == ItemStatus.DONT_NEED:
                status_code = "skipped"
                status_display = "Skipped"
            else:
                status_code = "need"
                status_display = "Need"

            is_available = status in (ItemStatus.GOT, ItemStatus.HAVE)
            is_skipped = status == ItemStatus.DONT_NEED
            is_need = status == ItemStatus.NEED
            is_missing = False
        else:
            status = None
            status_code = "missing"
            status_display = "Missing"
            is_available = False
            is_skipped = False
            is_need = False
            is_missing = True

        ingredients_with_status.append({
            "ingredient": ing,
            "item": item,
            "on_list": item is not None,
            "status": status,
            "status_code": status_code,
            "status_display": status_display,
            "is_ready": is_available,
            "is_available": is_available,
            "is_skipped": is_skipped,
            "is_need": is_need,
            "is_missing": is_missing,
            "is_optional": bool(ing.optional),
        })

    return ingredients_with_status


def compute_cooking_status(meal_plan: MealPlan | None, shopping_list: ShoppingList | None) -> dict[str, Any]:
    """
    Compute cooking readiness status for recipes, dishes, and meals:
    - 🟢 Green (Ready): 100% of recipe's ingredients (or the single item) are available (GOT or HAVE).
    - 🟡 Yellow (Missing optional or skipped): All non-optional, non-skipped ingredients are
      available (GOT or HAVE). The only missing ingredients are optional or explicitly skipped.
    - ⚪ Grey: One or more required non-skipped ingredients are still NEED or missing from list.

    Meal status:
    - 🟢 Green if all dishes in the meal are Green.
    - 🟡 Yellow if all dishes in the meal are either Green or Yellow (and >=1 is Yellow).
    - ⚪ Grey if any dish in the meal is Grey.

    Args:
        meal_plan: Target MealPlan.
        shopping_list: Workspace active ShoppingList.

    Returns:
        Dictionary mapping:
        {
            'recipes_ready': set of recipe ids,
            'recipes_missing_optional': set of recipe ids,
            'dishes_ready': set of MealDish ids,
            'dishes_missing_optional': set of MealDish ids,
            'meals_ready': set of meal ids,
            'meals_missing_optional': set of meal ids,
        }
    """
    empty_result = {
        "recipes_ready": set(),
        "recipes_missing_optional": set(),
        "dishes_ready": set(),
        "dishes_missing_optional": set(),
        "meals_ready": set(),
        "meals_missing_optional": set(),
    }
    if not meal_plan or not shopping_list:
        return empty_result

    recipes_ready = set()
    recipes_missing_optional = set()
    dishes_ready = set()
    dishes_missing_optional = set()

    all_meals = list(
        meal_plan.meals.prefetch_related(
            "recipes",
            "recipes__ingredients",
            "dishes",
            "dishes__recipe",
            "dishes__recipe__ingredients",
        ).all()
    )

    shopping_items = list(shopping_list.items.prefetch_related("attributions").all())
    item_by_dish_id: dict[int, ShoppingListItem] = {}
    for item in shopping_items:
        for attr in item.attributions.all():
            if attr.meal_dish_id and attr.recipe_id is None:
                item_by_dish_id[attr.meal_dish_id] = item
    exact_name_map = {item.name.strip().lower(): item for item in shopping_items}
    singular_name_map = {singularize(item.name.strip().lower()): item for item in shopping_items}

    # Cache recipe status so we only calculate each recipe once across meals
    recipe_status_cache: dict[int, str] = {}  # recipe_id -> "ready" | "missing_optional" | "grey"

    def _resolve_recipe_status(recipe: Recipe) -> str:
        if recipe.id in recipe_status_cache:
            return recipe_status_cache[recipe.id]

        ing_statuses = get_recipe_ingredients_status(recipe, shopping_list)
        if not ing_statuses:
            recipe_status_cache[recipe.id] = "ready"
            recipes_ready.add(recipe.id)
            return "ready"

        all_available = all(row["is_available"] for row in ing_statuses)
        all_but_optional_or_skipped = all(
            row["is_available"] or row["is_optional"] or row["is_skipped"]
            for row in ing_statuses
        )

        if all_available:
            recipe_status_cache[recipe.id] = "ready"
            recipes_ready.add(recipe.id)
            return "ready"
        if all_but_optional_or_skipped:
            recipe_status_cache[recipe.id] = "missing_optional"
            recipes_missing_optional.add(recipe.id)
            return "missing_optional"
        recipe_status_cache[recipe.id] = "grey"
        return "grey"

    def _resolve_single_item_dish_status(dish: MealDish) -> str:
        raw_name = (dish.item_name or "").strip().lower()
        norm_name = singularize(raw_name)
        item = (
            item_by_dish_id.get(dish.id)
            or exact_name_map.get(raw_name)
            or singular_name_map.get(norm_name)
        )
        if not item:
            return "grey"
        if item.status in (ItemStatus.GOT, ItemStatus.HAVE):
            return "ready"
        if item.status == ItemStatus.DONT_NEED:
            return "missing_optional"
        return "grey"

    for meal in all_meals:
        for recipe in meal.recipes.all():
            _resolve_recipe_status(recipe)

    meals_ready = set()
    meals_missing_optional = set()

    for meal in all_meals:
        dishes = list(meal.dishes.all())
        if dishes:
            dish_statuses: list[str] = []
            for dish in dishes:
                if dish.recipe:
                    st = _resolve_recipe_status(dish.recipe)
                else:
                    st = _resolve_single_item_dish_status(dish)
                if st == "ready":
                    dishes_ready.add(dish.id)
                elif st == "missing_optional":
                    dishes_missing_optional.add(dish.id)
                dish_statuses.append(st)

            total = len(dish_statuses)
            num_ready = sum(1 for st in dish_statuses if st == "ready")
            num_missing_opt = sum(1 for st in dish_statuses if st == "missing_optional")
            if num_ready == total:
                meals_ready.add(meal.id)
            elif (num_ready + num_missing_opt) == total:
                meals_missing_optional.add(meal.id)
        else:
            recipes = list(meal.recipes.all())
            recipe_count = len(recipes)
            if recipe_count == 0:
                continue

            num_ready = sum(1 for r in recipes if recipe_status_cache.get(r.id) == "ready")
            num_missing_opt = sum(1 for r in recipes if recipe_status_cache.get(r.id) == "missing_optional")

            if num_ready == recipe_count:
                meals_ready.add(meal.id)
            elif (num_ready + num_missing_opt) == recipe_count:
                meals_missing_optional.add(meal.id)

    return {
        "recipes_ready": recipes_ready,
        "recipes_missing_optional": recipes_missing_optional,
        "dishes_ready": dishes_ready,
        "dishes_missing_optional": dishes_missing_optional,
        "meals_ready": meals_ready,
        "meals_missing_optional": meals_missing_optional,
    }
