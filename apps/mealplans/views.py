"""
Views and HTMX endpoints for Meal Planning, recipe dish composition,
and ingredient synchronization with the active shopping list.
"""

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.services.moderation_service import contains_obscene_language
from apps.core.services.workspace_service import get_active_workspace
from apps.mealplans.models import ArchivedMeal, Meal, MealDish, MealPlanRule
from apps.mealplans.services.archive_service import (
    archive_made_meal,
    load_archived_meal_copy,
    rate_archived_meal,
    search_archived_meals,
)
from apps.mealplans.services.mealplan_service import (
    add_item_to_meal,
    add_meal_to_plan,
    add_recipe_to_meal,
    broadcast_mealplan_update,
    compute_cooking_status,
    delete_meal_from_plan,
    get_active_meal_plan,
    get_recipe_ingredients_status,
    mark_dish_as_made,
    remove_dish_from_meal,
    remove_recipe_from_meal,
    scale_meal_dish,
    update_meal_name,
)
from apps.mealplans.services.suggestion_service import (
    calculate_current_meal_nutrition,
    get_dish_suggestions,
)
from apps.recipes.models import Recipe, RecipeRating
from apps.recipes.services.recipe_service import (
    attach_recipe_made_counts,
    record_recipe_made,
    submit_recipe_rating,
)
from apps.shopping.views import get_active_list


def _resolve_meal_workspace(meal: Meal | None, fallback_workspace: Any) -> Any:
    """Return the meal plan workspace when available, else the active workspace."""
    if meal and meal.meal_plan and meal.meal_plan.workspace:
        return meal.meal_plan.workspace
    return fallback_workspace


def _build_mealplan_context(
    user: Any,
    workspace: Any,
    meal_plan: Any,
    shopping_list: Any,
    toast_messages: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Assemble shared meal plan rendering context with readiness statuses and dish metadata."""
    status_info = compute_cooking_status(meal_plan, shopping_list)
    available_recipes = Recipe.objects.all().order_by("name")
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else False
    meals = meal_plan.meals.prefetch_related("recipes", "dishes__recipe", "dishes__made_by").all() if meal_plan else []
    rules = meal_plan.rules.all() if meal_plan else []
    archived_count = ArchivedMeal.objects.filter(workspace=workspace).count() if workspace else 0
    context: dict[str, Any] = {
        "workspace": workspace,
        "shopping_list": shopping_list,
        "meal_plan": meal_plan,
        "meals": meals,
        "rules": rules,
        "recipes_ready": status_info["recipes_ready"],
        "recipes_missing_optional": status_info["recipes_missing_optional"],
        "dishes_ready": status_info["dishes_ready"],
        "dishes_missing_optional": status_info["dishes_missing_optional"],
        "dishes_made": status_info["dishes_made"],
        "meals_ready": status_info["meals_ready"],
        "meals_missing_optional": status_info["meals_missing_optional"],
        "available_recipes": available_recipes,
        "archived_count": archived_count,
        "can_write": can_write,
        "toast_messages": toast_messages or [],
    }
    context.update(extra)
    return context


def _check_mealplan_write(request: HttpRequest) -> HttpResponseForbidden | None:
    """Verify the user has edit/write permissions for the active workspace."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Authentication required.")
    workspace = get_active_workspace(request)
    if not workspace or not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")
    return None


def meal_plan_view(
    request: HttpRequest,
    toast_messages: list[str] | None = None,
) -> HttpResponse:
    """
    Render the Meal Plan management page or HTMX partial.
    """
    if not (request.user and request.user.is_authenticated):
        login_url = f"{reverse('core:login')}?next={request.path}"
        if request.headers.get("HX-Request"):
            resp = HttpResponse(status=401)
            resp["HX-Redirect"] = login_url
            return resp
        return redirect(login_url)

    workspace = get_active_workspace(request)
    shopping_list = get_active_list(request)
    meal_plan = get_active_meal_plan(request, workspace)

    user = getattr(request, "user", None)
    context = _build_mealplan_context(
        user=user,
        workspace=workspace,
        meal_plan=meal_plan,
        shopping_list=shopping_list,
        toast_messages=toast_messages,
    )

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
        is_obscene, _ = contains_obscene_language(meal_name)
        if is_obscene:
            msg = "Cannot add meal: Obscene or hurtful language is not permitted."
            messages.error(request, msg)
            toast_messages.append(f"❌ {msg}")
            return meal_plan_view(request, toast_messages=toast_messages)
        meal = add_meal_to_plan(meal_plan, meal_name)
        toast_messages.append(f"➕ Added '{meal.name}' to meal plan")
        actor = (request.user.first_name or "").strip() or request.user.username if request.user.is_authenticated else "Someone"
        broadcast_mealplan_update(
            request,
            toast_message=f"➕ {actor} added '{meal.name}' to meal plan",
            shopping_list=get_active_list(request),
        )

    return meal_plan_view(request, toast_messages=toast_messages)


def edit_meal(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Handle inline editing of a meal's name.
    GET: renders meal_name_form partial (or meal_header partial if ?cancel=1).
    POST: updates meal name, recomputes emoji, and returns updated meal plan view.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)

    if request.method == "POST":
        new_name = request.POST.get("name", "").strip()
        toast_messages: list[str] = []
        if new_name and new_name != meal.name:
            is_obscene, _ = contains_obscene_language(new_name)
            if is_obscene:
                toast_messages.append("❌ Cannot rename meal: Obscene or hurtful language is not permitted.")
                return meal_plan_view(request, toast_messages=toast_messages)
            old_name = meal.name
            update_meal_name(meal, new_name)
            toast_messages.append(f"✏️ Renamed '{old_name}' to '{meal.name}'")
            actor = (request.user.first_name or "").strip() or request.user.username if request.user.is_authenticated else "Someone"
            broadcast_mealplan_update(
                request,
                toast_message=f"✏️ {actor} renamed '{old_name}' to '{meal.name}'",
                shopping_list=get_active_list(request),
            )
        return meal_plan_view(request, toast_messages=toast_messages)

    if request.GET.get("cancel"):
        return render(request, "mealplans/partials/meal_header.html", {"meal": meal, "can_write": True})

    return render(request, "mealplans/partials/meal_name_form.html", {"meal": meal})


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
    actor = (request.user.first_name or "").strip() or request.user.username if request.user.is_authenticated else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"🗑 {actor} deleted '{meal_name}' from meal plan",
        shopping_list=shopping_list,
    )
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
    scale_raw = request.POST.get("scale_factor", "1").strip()
    try:
        scale_factor = Decimal(scale_raw)
        if scale_factor <= Decimal("0"):
            scale_factor = Decimal("1.00")
    except Exception:
        scale_factor = Decimal("1.00")

    recipe = None
    if recipe_id:
        recipe = Recipe.objects.filter(id=recipe_id).first()
    elif recipe_name:
        recipe = Recipe.objects.filter(name__iexact=recipe_name).first()

    toast_messages: list[str] = []
    if recipe:
        added_descriptions = add_recipe_to_meal(meal, recipe, shopping_list, request, scale_factor=scale_factor)
        scale_tag = f" ({scale_factor.normalize():f}x)" if scale_factor != Decimal("1.00") else ""
        count = len(added_descriptions)
        if count == 0:
            toast_messages.append(f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name}")
        elif count == 1:
            toast_messages.append(f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name} (1 ingredient added to shopping list)")
        else:
            toast_messages.append(f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name} ({count} ingredients added to shopping list)")

    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def add_single_item(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Handle POST request from the dedicated Single Item entry form on a meal card.
    Adds a single ingredient or shopping list item directly to the meal and onto
    the shopping list with the meal's name as its purpose.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    shopping_list = get_active_list(request)

    item_name = (request.POST.get("item_name") or request.POST.get("item") or "").strip()
    amount_raw = request.POST.get("amount", "").strip()
    unit_raw = request.POST.get("amount_unit", "").strip()
    scale_raw = request.POST.get("scale_factor", "1").strip()
    try:
        scale_factor = Decimal(scale_raw)
        if scale_factor <= Decimal("0"):
            scale_factor = Decimal("1.00")
    except Exception:
        scale_factor = Decimal("1.00")

    toast_messages: list[str] = []
    if item_name:
        is_obscene, _ = contains_obscene_language(f"{item_name} {amount_raw} {unit_raw}")
        if is_obscene:
            msg = "Cannot add item: Obscene or hurtful language is not permitted."
            messages.error(request, msg)
            toast_messages.append(f"❌ {msg}")
            return meal_plan_view(request, toast_messages=toast_messages)

        dish, _ = add_item_to_meal(
            meal=meal,
            raw_item_input=item_name,
            shopping_list=shopping_list,
            request=request,
            amount_override=amount_raw if amount_raw else None,
            unit_override=unit_raw if unit_raw else None,
            scale_factor=scale_factor,
        )
        toast_messages.append(
            f"🛒 Added single item '{dish.display_name}' ({dish.quantity_display}) to {meal.name} & shopping list"
        )

    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def scale_dish(request: HttpRequest, meal_id: int, dish_id: int) -> HttpResponse:
    """
    Update portion scaling factor for an individual planned dish.
    Recalculates contributed ingredient amounts on the shopping list.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    dish = MealDish.objects.filter(id=dish_id, meal=meal).first()
    if not dish:
        dish = MealDish.objects.filter(meal=meal, recipe_id=dish_id).first()
    if not dish:
        return HttpResponseForbidden("Dish not found.")

    if dish.is_made:
        return meal_plan_view(request, toast_messages=[f"'{dish.display_name}' was already marked as made."])

    shopping_list = get_active_list(request)
    scale_raw = request.POST.get("scale_factor", "1").strip()
    try:
        new_scale = Decimal(scale_raw)
        if new_scale <= Decimal("0"):
            new_scale = Decimal("1.00")
    except Exception:
        new_scale = Decimal("1.00")

    scale_meal_dish(dish, new_scale, shopping_list, request)

    scale_tag = f"{new_scale.normalize():f}x"
    dish_name = dish.display_name
    toast_messages = [f"⚖️ Scaled '{dish_name}' to {scale_tag}"]
    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"⚖️ {actor} scaled '{dish_name}' to {scale_tag}",
        shopping_list=shopping_list,
    )
    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def delete_dish(request: HttpRequest, meal_id: int, dish_id: int) -> HttpResponse:
    """
    Handle POST request to remove a recipe dish or single item from a meal.
    Accepts dish_id (targeting a specific occurrence) or recipe_id for backward compatibility.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    shopping_list = get_active_list(request)

    dish = MealDish.objects.filter(id=dish_id, meal=meal).first()
    if not dish:
        dish = MealDish.objects.filter(meal=meal, recipe_id=dish_id).first()

    if dish:
        dish_name = dish.display_name
        remove_dish_from_meal(dish, shopping_list, request)
    else:
        recipe = get_object_or_404(Recipe, id=dish_id)
        dish_name = recipe.name
        remove_recipe_from_meal(meal, recipe, shopping_list, request)

    toast_messages = [f"🗑 Removed '{dish_name}' from {meal.name} (ingredients updated on shopping list)"]
    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"🗑 {actor} removed '{dish_name}' from {meal.name}",
        shopping_list=shopping_list,
    )
    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def mark_dish_made(request: HttpRequest, meal_id: int, dish_id: int) -> HttpResponse:
    """
    Mark an individual recipe dish or single-item occurrence in a meal as made.
    Keeps the dish visible inside the meal with made timestamp & user attribution
    while deducting its ingredients from the shopping list and prompting for rating.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    dish = MealDish.objects.filter(id=dish_id, meal=meal).first()
    if not dish:
        dish = (
            MealDish.objects.filter(meal=meal, recipe_id=dish_id, made_at__isnull=True).first()
            or MealDish.objects.filter(meal=meal, recipe_id=dish_id).first()
        )

    shopping_list = get_active_list(request)
    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    user = getattr(request, "user", None)
    effective_workspace = _resolve_meal_workspace(meal, workspace)

    if dish and dish.is_made:
        context = _build_mealplan_context(
            user=user,
            workspace=effective_workspace,
            meal_plan=meal_plan,
            shopping_list=shopping_list,
            toast_messages=[f"✓ '{dish.display_name}' was already marked as made by {dish.made_actor_display}."],
            recipes=[],
            recipe=None,
            existing_ratings={},
            meal_name=meal.name,
            is_entire_meal=False,
        )
        return render(request, "mealplans/partials/recipe_rating_modal.html", context)

    if dish and dish.is_single_item:
        item_name = dish.display_name
        mark_dish_as_made(dish, user=user, shopping_list=shopping_list, request=request)
        toast_messages = [f"✓ Marked '{item_name}' as made (shopping list updated)"]
        context = _build_mealplan_context(
            user=user,
            workspace=effective_workspace,
            meal_plan=meal_plan,
            shopping_list=shopping_list,
            toast_messages=toast_messages,
            recipes=[],
            recipe=None,
            existing_ratings={},
            meal_name=meal.name,
            is_entire_meal=False,
        )
        return render(request, "mealplans/partials/recipe_rating_modal.html", context)

    if dish:
        recipe = dish.recipe
    else:
        recipe = get_object_or_404(Recipe, id=dish_id)

    # 1. Record recipe made & increment counter
    record_recipe_made(recipe, user=user, workspace=effective_workspace)
    attach_recipe_made_counts(recipe, user=user, workspace=effective_workspace)

    # 2. Mark dish as made (keeping it visible in the meal) & synchronize shopping list
    if dish:
        mark_dish_as_made(dish, user=user, shopping_list=shopping_list, request=request)
    else:
        remove_recipe_from_meal(meal, recipe, shopping_list, request)
        meal.recipes.add(recipe)
        legacy_dish = MealDish.objects.create(meal=meal, recipe=recipe)
        mark_dish_as_made(legacy_dish, user=user, shopping_list=None, request=request)

    # 3. Toast message & WebSocket broadcast already sent by mark_dish_as_made
    count_parts = [f"Made {recipe.times_made} time{'s' if recipe.times_made != 1 else ''} total"]
    if effective_workspace and recipe.workspace_made_count is not None:
        count_parts.append(f"Workspace: {recipe.workspace_made_count}")
    if user and getattr(user, "is_authenticated", False) and recipe.user_made_count is not None:
        count_parts.append(f"You: {recipe.user_made_count}")
    toast_messages = [
        f"✓ Marked '{recipe.name}' as made! ({' · '.join(count_parts)})"
    ]

    existing_rating = None
    if user and user.is_authenticated:
        existing_rating = RecipeRating.objects.filter(recipe=recipe, user=user).first()

    context = _build_mealplan_context(
        user=user,
        workspace=effective_workspace,
        meal_plan=meal_plan,
        shopping_list=shopping_list,
        toast_messages=toast_messages,
        recipes=[recipe],
        recipe=recipe,
        existing_ratings={recipe.id: existing_rating} if existing_rating else {},
        meal_name=meal.name,
        is_entire_meal=False,
    )
    return render(request, "mealplans/partials/recipe_rating_modal.html", context)


@require_POST
def mark_meal_made(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Mark an entire meal as made.
    Increments recipe times_made counter for each recipe dish in the meal, logs cooking events,
    removes the meal and all dishes (including single items) from the meal plan, and prompts
    for recipe ratings only on actual recipe dishes (single items are exempt).
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    meal = get_object_or_404(Meal, id=meal_id)
    shopping_list = get_active_list(request)
    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    user = getattr(request, "user", None)
    meal_name = meal.name

    effective_workspace = _resolve_meal_workspace(meal, workspace)
    dishes = list(
        meal.dishes.select_related("recipe", "made_by").prefetch_related("recipe__ingredients").all()
    )
    recipes = []
    toast_messages = []

    handled_recipe_ids = {dish.recipe_id for dish in dishes if dish.recipe_id}

    # Snapshot completed meal into per-workspace archive before removing dishes and deleting meal
    archive_made_meal(
        meal,
        dishes=dishes,
        user=user,
        workspace=effective_workspace,
        request=request,
    )

    # 1. Record made (only for dishes not already marked made) & clean up shopping items
    for dish in dishes:
        if dish.recipe and not dish.is_made:
            recipes.append(dish.recipe)
            record_recipe_made(dish.recipe, user=user, workspace=effective_workspace)
        remove_dish_from_meal(dish, shopping_list, request)

    # Fallback for any legacy recipes in M2M without MealDish
    for recipe in list(meal.recipes.all()):
        if recipe.id not in handled_recipe_ids and recipe not in recipes:
            recipes.append(recipe)
            record_recipe_made(recipe, user=user, workspace=effective_workspace)
            remove_recipe_from_meal(meal, recipe, shopping_list, request)

    attach_recipe_made_counts(recipes, user=user, workspace=effective_workspace)

    # 2. Delete the meal itself
    meal.delete()

    toast_messages.append(f"🍽 Marked entire meal '{meal_name}' as made, archived it, and removed from plan.")
    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"🍽 {actor} marked entire meal '{meal_name}' as made",
        shopping_list=shopping_list,
    )

    existing_ratings = {}
    if user and user.is_authenticated:
        for r in recipes:
            rating = RecipeRating.objects.filter(recipe=r, user=user).first()
            if rating:
                existing_ratings[r.id] = rating

    context = _build_mealplan_context(
        user=user,
        workspace=effective_workspace,
        meal_plan=meal_plan,
        shopping_list=shopping_list,
        toast_messages=toast_messages,
        recipes=recipes,
        existing_ratings=existing_ratings,
        meal_name=meal_name,
        is_entire_meal=True,
    )
    return render(request, "mealplans/partials/recipe_rating_modal.html", context)


@require_POST
def submit_made_ratings(request: HttpRequest) -> HttpResponse:
    """
    Handle submission of recipe ratings prompted after marking dishes as made.
    """
    user = getattr(request, "user", None)
    recipe_ids = request.POST.getlist("recipe_id")
    toast_messages = []

    if user and user.is_authenticated:
        for rid in recipe_ids:
            try:
                recipe = Recipe.objects.get(id=int(rid))
            except (ValueError, Recipe.DoesNotExist):
                continue

            stars_val = request.POST.get(f"stars_{rid}", "5")
            thumbs_val = request.POST.get(f"thumbs_up_{rid}") in ("true", "1", "on", True)
            try:
                stars = int(stars_val)
            except ValueError:
                stars = 5

            submit_recipe_rating(recipe, user, stars, thumbs_val)
            toast_messages.append(f"⭐ Saved {stars}★ rating for '{recipe.name}'")
    else:
        toast_messages.append("⭐ Rating noted! Log in to save ratings to your profile.")

    context = {
        "toast_messages": toast_messages,
    }
    return render(request, "mealplans/partials/rating_dismissed.html", context)


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

    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"🗑 {actor} cleared the meal plan",
        shopping_list=shopping_list,
    )

    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return meal_plan_view(request, toast_messages=["🗑 Cleared the entire meal plan"])
    return redirect("mealplans:detail")


def recipe_modal(request: HttpRequest, recipe_id: int) -> HttpResponse:
    """
    Render HTMX modal showing full recipe details, ingredients, and instructions.
    """
    recipe = get_object_or_404(Recipe, id=recipe_id)
    shopping_list = get_active_list(request)
    meal_id = request.GET.get("meal_id")
    dish_id = request.GET.get("dish_id")

    meal = Meal.objects.filter(id=meal_id).first() if meal_id else None
    meal_dish = MealDish.objects.filter(id=dish_id).first() if dish_id else None
    if not meal_dish and meal:
        meal_dish = MealDish.objects.filter(meal=meal, recipe=recipe).order_by("-created_at").first()

    is_recipe_updated_since_added = meal_dish.is_recipe_updated_since_added if meal_dish else False

    if not shopping_list and meal and meal.meal_plan and meal.meal_plan.workspace:
        shopping_list = meal.meal_plan.workspace.get_primary_list()

    # Check ingredient statuses on shopping list via centralized attribution resolver
    ingredients_with_status = get_recipe_ingredients_status(
        recipe=recipe,
        shopping_list=shopping_list,
        meal=meal,
        meal_dish=meal_dish,
    )

    total_ingredients = len(ingredients_with_status)
    need_count = sum(1 for row in ingredients_with_status if row["status_code"] in ("need", "missing"))
    got_count = sum(1 for row in ingredients_with_status if row["status_code"] == "got")
    have_count = sum(1 for row in ingredients_with_status if row["status_code"] == "have")
    skipped_count = sum(1 for row in ingredients_with_status if row["status_code"] == "skipped")
    ready_count = got_count + have_count

    workspace = get_active_workspace(request)
    effective_workspace = _resolve_meal_workspace(meal, workspace)
    meal_plan = get_active_meal_plan(request, workspace)
    user = getattr(request, "user", None)
    is_auth = bool(user and user.is_authenticated)
    can_write = effective_workspace.can_write(user) if (is_auth and effective_workspace) else False
    is_owner = is_auth and (
        (recipe.created_by == user)
        or (recipe.created_by is None)
        or getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
    )
    meals = meal_plan.meals.all() if meal_plan else []
    attach_recipe_made_counts(recipe, user=user, workspace=effective_workspace)

    context = {
        "workspace": effective_workspace,
        "recipe": recipe,
        "ingredients_with_status": ingredients_with_status,
        "total_ingredients": total_ingredients,
        "need_count": need_count,
        "got_count": got_count,
        "have_count": have_count,
        "skipped_count": skipped_count,
        "ready_count": ready_count,
        "is_recipe_updated_since_added": is_recipe_updated_since_added,
        "meal_dish": meal_dish,
        "meals": meals,
        "can_write": can_write,
        "is_owner": is_owner,
    }
    return render(request, "mealplans/partials/recipe_modal.html", context)


def meal_suggestions(request: HttpRequest, meal_id: int) -> HttpResponse:
    """
    Render dish suggestions partial for a planned meal.
    """
    meal = get_object_or_404(Meal, id=meal_id)
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated) or not meal.meal_plan.workspace.can_read(user):
        return HttpResponseForbidden("Access denied.")

    workspace = get_active_workspace(request)
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else False

    suggestions = get_dish_suggestions(meal, limit=5)
    current_nutrition = calculate_current_meal_nutrition(meal)

    context = {
        "meal": meal,
        "suggestions": suggestions,
        "current_nutrition": current_nutrition,
        "can_write": can_write,
    }
    return render(request, "mealplans/partials/dish_suggestions.html", context)


@require_POST
def add_meal_rule(request: HttpRequest) -> HttpResponse:
    """
    Handle POST request to add a new dietary/balance rule to the active meal plan.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    rule_text = request.POST.get("rule_text", "").strip()

    toast_messages: list[str] = []
    if rule_text:
        is_obscene, _ = contains_obscene_language(rule_text)
        if is_obscene:
            msg = "Cannot add guideline: Obscene or hurtful language is not permitted."
            messages.error(request, msg)
            toast_messages.append(f"❌ {msg}")
            return meal_plan_view(request, toast_messages=toast_messages)
        MealPlanRule.objects.create(meal_plan=meal_plan, rule_text=rule_text, is_active=True)
        toast_messages.append(f"📋 Added guideline: '{rule_text}'")
        actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
        broadcast_mealplan_update(
            request,
            toast_message=f"📋 {actor} added guideline: '{rule_text}'",
            shopping_list=get_active_list(request),
        )

    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def toggle_meal_rule(request: HttpRequest, rule_id: int) -> HttpResponse:
    """
    Toggle active/inactive state of a meal plan rule.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    rule = get_object_or_404(MealPlanRule, id=rule_id)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])

    status_str = "Enabled" if rule.is_active else "Paused"
    toast_messages = [f"📋 {status_str} guideline: '{rule.rule_text}'"]
    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"📋 {actor} {status_str.lower()} guideline: '{rule.rule_text}'",
        shopping_list=get_active_list(request),
    )
    return meal_plan_view(request, toast_messages=toast_messages)


@require_POST
def delete_meal_rule(request: HttpRequest, rule_id: int) -> HttpResponse:
    """
    Delete a meal plan rule.
    """
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    rule = get_object_or_404(MealPlanRule, id=rule_id)
    text = rule.rule_text
    rule.delete()

    toast_messages = [f"🗑 Removed guideline: '{text}'"]
    actor = (request.user.first_name or "").strip() or request.user.username if (request.user and request.user.is_authenticated) else "Someone"
    broadcast_mealplan_update(
        request,
        toast_message=f"🗑 {actor} removed guideline: '{text}'",
        shopping_list=get_active_list(request),
    )
    return meal_plan_view(request, toast_messages=toast_messages)


def _build_archive_results_context(request: HttpRequest, workspace: Any, user: Any) -> dict[str, Any]:
    """Extract shared search/sort params and assemble ArchivedMeals listing context."""
    params = request.POST if request.method == "POST" else request.GET
    q = (params.get("q") or "").strip()
    search_by = (params.get("search_by") or "all").strip()
    sort_by = (params.get("sort") or "recent").strip()
    embed = (params.get("embed") or "") == "1"
    can_write = workspace.can_write(user) if (user and user.is_authenticated and workspace) else False
    archived_meals = search_archived_meals(
        workspace,
        query=q,
        search_by=search_by,
        sort_by=sort_by,
    )
    return {
        "workspace": workspace,
        "archived_meals": archived_meals,
        "archive_query": q,
        "archive_search_by": search_by,
        "archive_sort_by": sort_by,
        "embed_in_mealplan": embed,
        "can_write": can_write,
    }


def archived_meals_view(request: HttpRequest) -> HttpResponse:
    """Render or search/sort per-workspace archived meals."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        login_url = f"{reverse('core:login')}?next={request.path}"
        if request.headers.get("HX-Request"):
            resp = HttpResponse(status=401)
            resp["HX-Redirect"] = login_url
            return resp
        return redirect(login_url)

    workspace = get_active_workspace(request)
    if not workspace or not workspace.can_read(user):
        return HttpResponseForbidden("Access denied.")

    context = _build_archive_results_context(request, workspace, user)
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        if request.GET.get("modal") == "1":
            return render(request, "mealplans/partials/archive_modal.html", context)
        if request.GET.get("panel") == "1":
            return render(request, "mealplans/partials/archived_meals_browser.html", context)
        return render(request, "mealplans/partials/archived_meals_results.html", context)
    return render(request, "mealplans/archived_meals.html", context)


@require_POST
def load_archived_meal(request: HttpRequest, archive_id: int) -> HttpResponse:
    """Load a copy of an archived meal and its dishes into the workspace's active Meal Plan."""
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    archived_meal = get_object_or_404(ArchivedMeal, id=archive_id, workspace=workspace)
    meal_plan = get_active_meal_plan(request, workspace)
    shopping_list = get_active_list(request)
    custom_name = (request.POST.get("name") or "").strip() or None

    new_meal, dishes_loaded, _ = load_archived_meal_copy(
        archived_meal,
        meal_plan,
        shopping_list,
        request=request,
        custom_name=custom_name,
    )
    toast = (
        f"📋 Loaded copy of '{new_meal.name}' "
        f"({dishes_loaded} dish{'es' if dishes_loaded != 1 else ''}) into Meal Plan"
    )
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "mealplan-content":
        return meal_plan_view(request, toast_messages=[toast])
    messages.success(request, toast)
    return redirect("mealplans:detail")


@require_POST
def rate_archived_meal_view(request: HttpRequest, archive_id: int) -> HttpResponse:
    """Set or update the star rating for an archived meal."""
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    archived_meal = get_object_or_404(ArchivedMeal, id=archive_id, workspace=workspace)
    raw_rating = (request.POST.get("rating") or "").strip()
    try:
        stars = int(raw_rating) if raw_rating else None
    except ValueError:
        stars = None
    if stars is not None and stars <= 0:
        stars = None
    rate_archived_meal(archived_meal, stars)

    if request.headers.get("HX-Request"):
        context = _build_archive_results_context(request, workspace, getattr(request, "user", None))
        return render(request, "mealplans/partials/archived_meals_results.html", context)
    return redirect("mealplans:archive")


@require_POST
def delete_archived_meal_view(request: HttpRequest, archive_id: int) -> HttpResponse:
    """Delete an archived meal entry from the workspace archive."""
    forbidden = _check_mealplan_write(request)
    if forbidden:
        return forbidden

    workspace = get_active_workspace(request)
    archived_meal = get_object_or_404(ArchivedMeal, id=archive_id, workspace=workspace)
    archived_meal.delete()

    if request.headers.get("HX-Request"):
        context = _build_archive_results_context(request, workspace, getattr(request, "user", None))
        return render(request, "mealplans/partials/archived_meals_results.html", context)
    return redirect("mealplans:archive")
