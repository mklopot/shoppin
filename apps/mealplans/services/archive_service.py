"""
Service layer for archiving completed (made) meals per workspace,
searching and sorting archived meals by title words, dish, ingredient, or rating,
and loading fresh copies of archived meals back into a workspace's active Meal Plan.
"""

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Avg, F, FloatField, OrderBy, Q
from django.db.models.functions import Cast, Coalesce
from django.http import HttpRequest
from django.utils import timezone

from apps.core.utils import singularize
from apps.mealplans.models import ArchivedMeal, ArchivedMealDish, Meal, MealDish, MealPlan
from apps.mealplans.services.mealplan_service import (
    add_item_to_meal,
    add_meal_to_plan,
    add_recipe_to_meal,
    broadcast_mealplan_update,
)
from apps.shopping.models import ShoppingList


def _resolve_actor_info(user: Any = None, request: HttpRequest | None = None) -> tuple[Any | None, str]:
    """Resolve authenticated actor user and clean display name."""
    actor = user
    if not (actor and getattr(actor, "is_authenticated", False)) and request is not None:
        req_user = getattr(request, "user", None)
        if req_user and getattr(req_user, "is_authenticated", False):
            actor = req_user
    if actor and getattr(actor, "is_authenticated", False):
        first_name = (getattr(actor, "first_name", "") or "").strip()
        return actor, (first_name or actor.username)
    return None, "Someone"


def archive_made_meal(
    meal: Meal,
    *,
    dishes: list[MealDish] | None = None,
    user: Any = None,
    workspace: Any = None,
    request: HttpRequest | None = None,
) -> ArchivedMeal | None:
    """
    Create a per-workspace ArchivedMeal snapshot of a meal and its dishes when marked made.
    """
    target_workspace = workspace or (meal.meal_plan.workspace if meal.meal_plan else None)
    if not target_workspace:
        return None

    now = timezone.now()
    actor_user, actor_name = _resolve_actor_info(user=user, request=request)

    archived_meal = ArchivedMeal.objects.create(
        workspace=target_workspace,
        name=meal.name,
        emoji=meal.emoji or "",
        made_at=now,
        made_by=actor_user,
        made_by_name=actor_name[:150],
    )

    dish_rows = dishes if dishes is not None else list(
        meal.dishes.select_related("recipe", "made_by").prefetch_related("recipe__ingredients").all()
    )
    handled_recipe_ids: set[int] = set()

    for idx, dish in enumerate(dish_rows):
        if dish.recipe_id:
            handled_recipe_ids.add(dish.recipe_id)
        if dish.is_single_item:
            ing_names = (dish.item_name or "").strip()
            dish_title = ing_names
        elif dish.recipe:
            ing_names = ", ".join(
                ing.name.strip() for ing in dish.recipe.ingredients.all() if ing.name and ing.name.strip()
            )
            dish_title = dish.recipe.name
        else:
            ing_names = ""
            dish_title = dish.display_name

        d_made_at = dish.made_at or now
        d_made_by = dish.made_by or actor_user
        d_made_by_name = dish.made_by_name or actor_name

        ArchivedMealDish.objects.create(
            archived_meal=archived_meal,
            recipe=dish.recipe if not dish.is_single_item else None,
            is_single_item=dish.is_single_item,
            dish_name=dish_title[:255],
            item_name=(dish.item_name or "")[:255],
            amount=dish.amount,
            amount_unit=dish.amount_unit,
            scale_factor=dish.scale_factor,
            order=dish.order if dish.order is not None else idx,
            ingredient_names_text=ing_names,
            made_at=d_made_at,
            made_by=d_made_by,
            made_by_name=d_made_by_name[:150],
        )

    # Preserve any legacy M2M recipe entries not backed by MealDish
    for offset, recipe in enumerate(meal.recipes.prefetch_related("ingredients").all(), start=len(dish_rows)):
        if recipe.id in handled_recipe_ids:
            continue
        ing_names = ", ".join(
            ing.name.strip() for ing in recipe.ingredients.all() if ing.name and ing.name.strip()
        )
        ArchivedMealDish.objects.create(
            archived_meal=archived_meal,
            recipe=recipe,
            is_single_item=False,
            dish_name=recipe.name[:255],
            order=offset,
            ingredient_names_text=ing_names,
            made_at=now,
            made_by=actor_user,
            made_by_name=actor_name[:150],
        )

    return archived_meal


def _build_word_filter(word: str, search_by: str) -> Q:
    """Build case-insensitive Q filter matching word (and singularized stem) within scope."""
    variants = {word}
    sing = singularize(word.lower())
    if sing:
        variants.add(sing)

    combined = Q()
    for term in variants:
        title_q = Q(name__icontains=term)
        dish_q = (
            Q(dishes__dish_name__icontains=term)
            | Q(dishes__recipe__name__icontains=term)
            | Q(dishes__item_name__icontains=term)
        )
        ing_q = (
            Q(dishes__recipe__ingredients__name__icontains=term)
            | Q(dishes__ingredient_names_text__icontains=term)
        )
        if search_by == "title":
            combined |= title_q
        elif search_by == "dish":
            combined |= dish_q
        elif search_by == "ingredient":
            combined |= ing_q
        else:
            combined |= title_q | dish_q | ing_q
    return combined


def search_archived_meals(
    workspace: Any,
    *,
    query: str = "",
    search_by: str = "all",
    sort_by: str = "recent",
    limit: int | None = None,
) -> list[ArchivedMeal]:
    """
    Search and sort workspace ArchivedMeals by words in title, dish name,
    ingredient name, or star rating.
    """
    if not workspace:
        return []

    scope = (search_by or "all").strip().lower()
    if scope not in ("all", "title", "dish", "ingredient"):
        scope = "all"

    sort_key = (sort_by or "recent").strip().lower()

    base_qs = ArchivedMeal.objects.filter(workspace=workspace)
    words = [w.strip() for w in re.split(r"\s+", (query or "").strip()) if w.strip()]
    for word in words:
        base_qs = base_qs.filter(_build_word_filter(word, scope))

    # Subquery avoids row multiplication on Avg when filters join dishes/ingredients
    matched_ids = base_qs.values("id").distinct()
    qs = ArchivedMeal.objects.filter(id__in=matched_ids).annotate(
        recipe_avg_rating=Avg("dishes__recipe__ratings__stars"),
        effective_rating=Coalesce(
            Cast("rating", FloatField()),
            F("recipe_avg_rating"),
            output_field=FloatField(),
        ),
    ).select_related("made_by").prefetch_related(
        "dishes__recipe__ingredients",
        "dishes__recipe__ratings",
        "dishes__made_by",
    )

    if sort_key in ("rating", "rating_desc"):
        qs = qs.order_by(
            OrderBy(F("effective_rating"), descending=True, nulls_last=True),
            "-made_at",
            "-id",
        )
    elif sort_key == "rating_asc":
        qs = qs.order_by(
            OrderBy(F("effective_rating"), descending=False, nulls_last=True),
            "-made_at",
            "-id",
        )
    elif sort_key == "name":
        qs = qs.order_by("name", "-made_at", "-id")
    else:
        qs = qs.order_by("-made_at", "-id")

    if limit and limit > 0:
        qs = qs[:limit]

    return list(qs)


def load_archived_meal_copy(
    archived_meal: ArchivedMeal,
    meal_plan: MealPlan,
    shopping_list: ShoppingList,
    *,
    request: HttpRequest | None = None,
    custom_name: str | None = None,
) -> tuple[Meal, int, int]:
    """
    Load a fresh unmade copy of an archived meal and its dishes into the active Meal Plan,
    populating ingredients onto the active shopping list.
    """
    target_name = (custom_name or archived_meal.name).strip() or archived_meal.name
    new_meal = add_meal_to_plan(meal_plan, target_name)
    if archived_meal.emoji and new_meal.emoji != archived_meal.emoji:
        new_meal.emoji = archived_meal.emoji
        new_meal.save(update_fields=["emoji"])

    dishes_loaded = 0
    shopping_items_added = 0

    for arch_dish in archived_meal.dishes.select_related("recipe").order_by("order", "id"):
        if not arch_dish.is_single_item and arch_dish.recipe:
            try:
                added_descs = add_recipe_to_meal(
                    new_meal,
                    arch_dish.recipe,
                    shopping_list,
                    request=request,
                    scale_factor=arch_dish.scale_factor,
                )
                dishes_loaded += 1
                shopping_items_added += len(added_descs)
                continue
            except ValidationError:
                pass

        item_label = arch_dish.item_name or arch_dish.dish_name
        if item_label:
            add_item_to_meal(
                new_meal,
                item_label,
                shopping_list,
                request=request,
                amount_override=str(arch_dish.amount),
                unit_override=arch_dish.amount_unit,
                scale_factor=arch_dish.scale_factor,
            )
            dishes_loaded += 1
            shopping_items_added += 1

    _, actor_name = _resolve_actor_info(request=request)
    if shopping_list:
        broadcast_mealplan_update(
            request,
            toast_message=f"📋 {actor_name} loaded archived meal '{new_meal.name}' into the meal plan",
            shopping_list=shopping_list,
        )

    return new_meal, dishes_loaded, shopping_items_added


def rate_archived_meal(archived_meal: ArchivedMeal, stars: int | None) -> ArchivedMeal:
    """Persist or clear an explicit 1-5 star rating on an ArchivedMeal."""
    if stars is None:
        archived_meal.rating = None
    else:
        archived_meal.rating = max(1, min(5, int(stars)))
    archived_meal.save(update_fields=["rating"])
    return archived_meal


__all__ = [
    "archive_made_meal",
    "load_archived_meal_copy",
    "rate_archived_meal",
    "search_archived_meals",
]
