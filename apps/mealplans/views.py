"""
Views and HTMX endpoints for Meal Planning, recipe dish composition,
and ingredient synchronization with the active shopping list.
"""

from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.services.workspace_service import get_active_workspace
from apps.mealplans.models import Meal
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    compute_cooking_status,
    delete_meal_from_plan,
    get_active_meal_plan,
    remove_recipe_from_meal,
)
from apps.recipes.models import Recipe
from apps.shopping.views import get_active_list


def _check_mealplan_write(request: HttpRequest) -> HttpResponseForbidden | None:
    """Verify the user has edit/write permissions for the active workspace."""
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        workspace = get_active_workspace(request)
        if workspace and not workspace.can_write(user):
            return HttpResponseForbidden("You have read-only access to this workspace.")
    return None


def meal_plan_view(
    request: HttpRequest,
    toast_messages: list[str] | None = None,
) -> HttpResponse:
    """
    Render the Meal Plan management page or HTMX partial.
    """
    workspace = get_active_workspace(request)
    shopping_list = get_active_list(request)
    meal_plan = get_active_meal_plan(request, workspace)

    status_info = compute_cooking_status(meal_plan, shopping_list)
    available_recipes = Recipe.objects.all().order_by("name")

    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else True

    meals = meal_plan.meals.prefetch_related("recipes").all()

    context: dict[str, Any] = {
        "workspace": workspace,
        "shopping_list": shopping_list,
        "meal_plan": meal_plan,
        "meals": meals,
        "recipes_ready": status_info["recipes_ready"],
        "recipes_missing_optional": status_info["recipes_missing_optional"],
        "meals_ready": status_info["meals_ready"],
        "meals_missing_optional": status_info["meals_missing_optional"],
        "available_recipes": available_recipes,
        "can_write": can_write,
        "toast_messages": toast_messages or [],
    }

    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return render(request, "mealplans/partials/mealplan_content.html", context)
    return render(request, "mealplans/mealplan_detail.html", context)


@require_POST
def add_meal(request: HttpRequest) -> HttpResponse:
    """
    Handle POST request to add a new meal to the meal plan.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)

    meal_name = request.POST.get("meal", "").strip()
    toast_messages: list[str] = []
    if meal_name:
        meal = add_meal_to_plan(meal_plan, meal_name)
        toast_messages.append(f"➕ Added '{meal.name}' to meal plan")

    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def delete_meal(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Handle POST request to delete a meal and its shopping list ingredients.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    meal_name = meal.name
    shopping_list = get_active_list(request)
    delete_meal_from_plan(meal, shopping_list, request)

    toast_messages = [f"🗑 Deleted '{meal_name}' from meal plan"]
    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def add_dish(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Handle POST request to add a recipe dish to a meal.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    shopping_list = get_active_list(request)

    recipe_name = request.POST.get("recipe", "").strip()
    recipe_id = request.POST.get("recipe_id")

    recipe = None
    if recipe_id:
        recipe = Recipe.objects.filter(id=recipe_id).first()
    elif recipe_name:
        recipe = Recipe.objects.filter(name__iexact=recipe_name).first()

    toast_messages: list[str] = []
    if recipe:
        added_descriptions = add_recipe_to_meal(meal, recipe, shopping_list, request)
        toast_messages.append(f"🥘 Added '{recipe.name}' to {meal.name}")
        if len(added_descriptions) <= 6:
            for desc in added_descriptions:
                toast_messages.append(f"🛒 Added {desc} to shopping list")
        else:
            for desc in added_descriptions[:5]:
                toast_messages.append(f"🛒 Added {desc} to shopping list")
            remaining = len(added_descriptions) - 5
            toast_messages.append(f"🛒 ...and {remaining} more ingredients added to shopping list")

    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def delete_dish(request: HttpRequest, meal_id: int, recipe_id: int) -> HttpResponse:
    """
    Handle POST request to remove a recipe dish from a meal.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    recipe = get_object_or_404(Recipe, id=recipe_id)
    shopping_list = get_active_list(request)

    remove_recipe_from_meal(meal, recipe, shopping_list, request)

    toast_messages = [f"🗑 Removed '{recipe.name}' from {meal.name} (ingredients updated on shopping list)"]
    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def clear_meal_plan(request: HttpRequest) -> HttpResponse:
    """
    Clear all meals from the meal plan and remove their ingredients from the shopping list.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    shopping_list = get_active_list(request)

    for meal in meal_plan.meals.all():
        delete_meal_from_plan(meal, shopping_list, request)

    return redirect("mealplans:detail")


def recipe_modal(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Render HTMX modal showing full recipe details, ingredients, and instructions.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    shopping_list = get_active_list(request)

    # Check ingredient statuses on shopping list
    items_by_name = {it.name.lower(): it for it in shopping_list.items.all()}
    ingredients_with_status = []
    for ing in recipe.ingredients.all():
        item = items_by_name.get(ing.name.lower())
        ingredients_with_status.append({
            "ingredient": ing,
            "on_list": item is not None,
            "status": item.status if item else None,
            "is_ready": item.status in ("GOT", "HAVE") if item else False,
        })

    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else True
    meals = meal_plan.meals.all()

    context = {
        "recipe": recipe,
        "ingredients_with_status": ingredients_with_status,
        "meals": meals,
        "can_write": can_write,
    }
    return render(request, "mealplans/partials/recipe_modal.html", context)
