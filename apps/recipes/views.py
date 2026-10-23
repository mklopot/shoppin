"""
Views for culinary recipes, interactive multi-facet search, detail, ratings, and creation.
"""

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.services.workspace_service import get_active_workspace
from apps.mealplans.models import Meal
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    get_active_meal_plan,
)
from apps.recipes.models import Recipe, RecipeRating
from apps.recipes.services.recipe_service import (
    add_recipe_to_shopping_list,
    create_or_update_recipe,
    get_filter_options,
    search_recipes,
    submit_recipe_rating,
)
from apps.shopping.views import get_active_list


def recipe_list_view(request: HttpRequest) -> HttpResponse:
    """
    Render the main Recipes directory page or HTMX filtered results grid.
    """
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else True

    params: dict[str, Any] = {
        "q": request.GET.get("q", "").strip(),
        "cuisine": request.GET.get("cuisine", "").strip(),
        "dish_type": request.GET.get("dish_type", "").strip(),
        "meal_type": request.GET.get("meal_type", "").strip(),
        "dietary": request.GET.get("dietary", "").strip(),
        "occasion": request.GET.get("occasion", "").strip(),
        "difficulty": request.GET.get("difficulty", "").strip(),
        "equipment": request.GET.get("equipment", "").strip(),
        "sort": request.GET.get("sort", "name").strip(),
    }

    recipes = search_recipes(params)
    filter_options = get_filter_options()

    active_filter_count = sum(
        1 for k, v in params.items()
        if k != "sort" and v and v.lower() != "all"
    )

    context: dict[str, Any] = {
        "workspace": workspace,
        "recipes": recipes,
        "recipe_count": recipes.count(),
        "filter_options": filter_options,
        "params": params,
        "active_filter_count": active_filter_count,
        "can_write": can_write,
    }

    # Render HTMX partial when filtering without full page reload
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return render(request, "recipes/partials/recipe_grid.html", context)

    return render(request, "recipes/recipe_list.html", context)


def recipe_detail_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Render full recipe detail page or HTMX quick-view modal.
    """
    recipe = get_object_or_404(
        Recipe.objects.prefetch_related("ingredients", "serve_with", "ratings", "comments"),
        id=recipe_id,
    )
    workspace = get_active_workspace(request)
    shopping_list = get_active_list(request)
    meal_plan = get_active_meal_plan(request, workspace)

    user = getattr(request, "user", None)
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else True

    user_rating = None
    if user and user.is_authenticated:
        user_rating = RecipeRating.objects.filter(recipe=recipe, user=user).first()

    context: dict[str, Any] = {
        "workspace": workspace,
        "shopping_list": shopping_list,
        "meal_plan": meal_plan,
        "recipe": recipe,
        "ingredients": recipe.ingredients.all(),
        "serve_with_recipes": recipe.serve_with.all(),
        "user_rating": user_rating,
        "can_write": can_write,
        "meals": meal_plan.meals.all() if meal_plan else [],
    }

    if request.headers.get("HX-Request") and request.GET.get("modal") == "1":
        return render(request, "recipes/partials/recipe_modal.html", context)

    return render(request, "recipes/recipe_detail.html", context)


def recipe_create_view(request: HttpRequest) -> HttpResponse:
    """
    Create a new recipe entry.
    """
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        recipe = create_or_update_recipe(request.POST, files=request.FILES, user=user)
        messages.success(request, f"Recipe '{recipe.name}' created successfully!")
        return redirect("recipes:detail", recipe_id=recipe.id)

    filter_options = get_filter_options()
    all_recipes = Recipe.objects.all().order_by("name")

    context: dict[str, Any] = {
        "workspace": workspace,
        "filter_options": filter_options,
        "all_recipes": all_recipes,
        "is_edit": False,
    }
    return render(request, "recipes/recipe_form.html", context)


def recipe_edit_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Edit an existing recipe entry and ingredients.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        create_or_update_recipe(request.POST, files=request.FILES, recipe_id=recipe.id, user=user)
        messages.success(request, f"Recipe '{recipe.name}' updated successfully!")
        return redirect("recipes:detail", recipe_id=recipe.id)

    filter_options = get_filter_options()
    all_recipes = Recipe.objects.exclude(id=recipe.id).order_by("name")

    context: dict[str, Any] = {
        "workspace": workspace,
        "recipe": recipe,
        "ingredients": recipe.ingredients.all(),
        "filter_options": filter_options,
        "all_recipes": all_recipes,
        "is_edit": True,
    }
    return render(request, "recipes/recipe_form.html", context)


@require_POST
def recipe_delete_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Delete a recipe entry.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    name = recipe.name
    recipe.delete()
    messages.success(request, f"Recipe '{name}' was deleted.")
    return redirect("recipes:list")


@require_POST
def recipe_rate_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Handle user rating and endorsement (stars and thumbs-up).
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to rate recipes.")

    stars = int(request.POST.get("stars", 5))
    thumbs_up = request.POST.get("thumbs_up") in ("true", "1", True)

    rating = submit_recipe_rating(recipe, user, stars, thumbs_up)

    context = {
        "recipe": recipe,
        "user_rating": rating,
    }
    return render(request, "recipes/partials/rating_widget.html", context)


@require_POST
def recipe_add_to_shopping_list_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Add all recipe ingredients directly to the active shopping list.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    shopping_list = get_active_list(request)

    added = add_recipe_to_shopping_list(recipe, shopping_list, request)

    toast_msg = f"🛒 Added '{recipe.name}' ({len(added)} ingredients) to Shopping List"
    context = {
        "toast_message": toast_msg,
    }
    return render(request, "recipes/partials/toast_oob.html", context)


@require_POST
def recipe_add_to_mealplan_view(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Add a recipe to a meal plan meal entry.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    shopping_list = get_active_list(request)

    meal_id = request.POST.get("meal_id")
    meal_name = request.POST.get("meal_name", "").strip()

    if meal_id:
        meal = get_object_or_404(Meal, id=meal_id, meal_plan=meal_plan)
    else:
        target_name = meal_name or f"{recipe.name} Dinner"
        meal = add_meal_to_plan(meal_plan, target_name)

    added_descriptions = add_recipe_to_meal(meal, recipe, shopping_list, request)

    toast_msg = f"🥘 Added '{recipe.name}' to {meal.name} and loaded {len(added_descriptions)} ingredients onto Shopping List"
    context = {
        "toast_message": toast_msg,
    }
    return render(request, "recipes/partials/toast_oob.html", context)
