"""
Views for culinary recipes, interactive multi-facet search, detail, ratings, and creation.
"""

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.services.workspace_service import get_active_workspace
from apps.mealplans.models import Meal
from apps.mealplans.services.mealplan_service import (
    add_meal_to_plan,
    add_recipe_to_meal,
    get_active_meal_plan,
)
from apps.recipes.models import Recipe, RecipeRating
from apps.recipes.services.recipe_scraper import import_recipe_from_url, scrape_recipe_data
from apps.recipes.services.recipe_service import (
    create_or_update_recipe,
    get_filter_options,
    search_recipes,
    submit_recipe_rating,
)
from apps.shopping.views import get_active_list


def _get_recipe_by_id_or_slug(
    recipe_id: int | None = None,
    slug: str | None = None,
    prefetch: bool = False,
) -> Recipe:
    """
    Retrieve recipe by numeric primary key or human-readable slug.
    """
    qs = Recipe.objects.all()
    if prefetch:
        qs = qs.prefetch_related("ingredients", "serve_with", "ratings", "comments")
    if recipe_id is not None:
        return get_object_or_404(qs, id=recipe_id)
    if slug:
        return get_object_or_404(qs, slug=slug)
    raise Http404("Recipe not found")


def recipe_list_view(request: HttpRequest) -> HttpResponse:
    """
    Render the main Recipes directory page or HTMX filtered results grid.
    Publicly published and moderator-approved recipes are visible without being logged in.
    """
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    can_write = workspace.can_write(user) if (is_authenticated and workspace) else False

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

    recipes = search_recipes(params, user=user)
    filter_options = get_filter_options()
    meal_plan = get_active_meal_plan(request, workspace) if is_authenticated else None
    meals = meal_plan.meals.all() if meal_plan else []

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
        "meal_plan": meal_plan,
        "meals": meals,
    }

    # Render HTMX partial when filtering without full page reload
    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return render(request, "recipes/partials/recipe_grid.html", context)

    return render(request, "recipes/recipe_list.html", context)


def recipe_detail_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Render full recipe detail page or HTMX quick-view modal.

    Accepts either an ID or straightforward slug URL (e.g. /recipes/crepes/).
    Publicly published and moderator-approved recipes are visible without being logged in.
    """
    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug, prefetch=True)
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)

    # Visibility & Moderation Access Control:
    # Public & approved recipes can be viewed by anyone without logging in.
    # Private or unapproved recipes require authentication and creator/moderator privileges.
    if not (recipe.is_public and recipe.is_approved):
        if not is_authenticated:
            messages.info(request, "This recipe is private or pending moderator approval. Please sign in to view it.")
            return redirect(f"{reverse('core:login')}?next={request.path}")
        if recipe.created_by != user and not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
            return HttpResponseForbidden("This recipe is private or pending moderator approval.")

    workspace = get_active_workspace(request)
    shopping_list = get_active_list(request) if is_authenticated else None
    meal_plan = get_active_meal_plan(request, workspace) if is_authenticated else None

    can_write = workspace.can_write(user) if (is_authenticated and workspace) else False

    user_rating = None
    if is_authenticated:
        user_rating = RecipeRating.objects.filter(recipe=recipe, user=user).first()

    context: dict[str, Any] = {
        "workspace": workspace,
        "shopping_list": shopping_list,
        "meal_plan": meal_plan,
        "recipe": recipe,
        "ingredients": recipe.ingredients.all(),
        "serve_with_recipes": recipe.serve_with.filter(is_public=True, is_approved=True) if not is_authenticated else recipe.serve_with.all(),
        "user_rating": user_rating,
        "can_write": can_write,
        "meals": meal_plan.meals.all() if meal_plan else [],
    }

    if request.headers.get("HX-Request") and request.GET.get("modal") == "1":
        return render(request, "recipes/partials/recipe_modal.html", context)

    return render(request, "recipes/recipe_detail.html", context)


def recipe_create_view(request: HttpRequest) -> HttpResponse:
    """
    Create a new recipe entry. Requires authentication.

    Optionally accepts ?import_url=<url> to scrape and pre-populate the form.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to create or import recipes.")
        return redirect(f"{reverse('core:login')}?next={request.path}")

    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        try:
            recipe = create_or_update_recipe(request.POST, files=request.FILES, user=user)
            messages.success(request, f"Recipe '{recipe.name}' created successfully!")
            return redirect(recipe.get_absolute_url())
        except ValidationError as ve:
            err_msg = getattr(ve, "message", None) or (ve.messages[0] if getattr(ve, "messages", None) else str(ve))
            messages.error(request, err_msg)

    filter_options = get_filter_options()
    all_recipes = Recipe.objects.all().order_by("name")

    recipe = None
    ingredients = []
    import_url = request.GET.get("import_url", "").strip()
    if import_url:
        try:
            data = scrape_recipe_data(import_url)
            recipe = Recipe(
                name=data["name"],
                description=data["description"],
                directions=data["directions"],
                portions=data["portions"],
                prep_time_minutes=data["prep_time_minutes"],
                cook_time_minutes=data["cook_time_minutes"],
                cuisine=data["cuisine"],
                dish_type=data["dish_type"],
                photo_urls=[data["photo_url"]] if data["photo_url"] else [],
                bibliography=[data["source_url"]],
            )
            ingredients = data["ingredients"]
            messages.info(
                request,
                f"Pre-filled recipe from {data['domain']}. Review the details and ingredients below, then save.",
            )
        except Exception as exc:
            messages.error(request, f"Could not scrape recipe from URL: {exc}")

    context: dict[str, Any] = {
        "workspace": workspace,
        "filter_options": filter_options,
        "all_recipes": all_recipes,
        "recipe": recipe,
        "ingredients": ingredients,
        "import_url": import_url,
        "is_edit": False,
    }
    return render(request, "recipes/recipe_form.html", context)


@require_POST
def recipe_import_url_view(request: HttpRequest) -> HttpResponse:
    """
    Import a recipe from an external webpage URL.

    Actions:
    - 'direct': Scrapes, saves immediately into database, and redirects to recipe detail.
    - 'prefill': Scrapes and redirects to create form pre-filled for user review.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to import recipes.")
        return redirect(f"{reverse('core:login')}?next={reverse('recipes:list')}")

    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    url = (request.POST.get("url") or "").strip()
    action = request.POST.get("action", "direct").strip()

    if not url:
        messages.error(request, "Please enter a valid recipe webpage URL.")
        return redirect("recipes:list")

    if action == "prefill":
        from urllib.parse import urlencode

        return redirect(f"{reverse('recipes:create')}?{urlencode({'import_url': url})}")

    try:
        recipe = import_recipe_from_url(url=url, user=user)
        messages.success(request, f"Recipe '{recipe.name}' successfully imported!")
        return redirect(recipe.get_absolute_url())
    except ValueError as ve:
        messages.error(request, str(ve))
        return redirect("recipes:list")
    except Exception as exc:
        messages.error(request, f"Could not import recipe from '{url}': {exc}")
        return redirect("recipes:list")


def recipe_edit_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Edit an existing recipe entry and ingredients.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to edit recipes.")
        return redirect(f"{reverse('core:login')}?next={request.path}")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        try:
            create_or_update_recipe(request.POST, files=request.FILES, recipe_id=recipe.id, user=user)
            messages.success(request, f"Recipe '{recipe.name}' updated successfully!")
            return redirect(recipe.get_absolute_url())
        except ValidationError as ve:
            err_msg = getattr(ve, "message", None) or (ve.messages[0] if getattr(ve, "messages", None) else str(ve))
            messages.error(request, err_msg)

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
def recipe_delete_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Delete a recipe entry.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to delete recipes.")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    name = recipe.name
    recipe.delete()
    messages.success(request, f"Recipe '{name}' was deleted.")
    return redirect("recipes:list")


@require_POST
def recipe_rate_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Handle user rating and endorsement (stars and thumbs-up).
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to rate recipes.")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    stars = int(request.POST.get("stars", 5))
    thumbs_up = request.POST.get("thumbs_up") in ("true", "1", True)

    rating = submit_recipe_rating(recipe, user, stars, thumbs_up)

    context = {
        "recipe": recipe,
        "user_rating": rating,
    }
    return render(request, "recipes/partials/rating_widget.html", context)


def recipe_prompt_mealplan_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Render HTMX modal prompting the user to select or create a meal for the recipe.
    """
    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to add recipes to your meal plan.")
        return redirect(f"{reverse('core:login')}?next={recipe.get_absolute_url()}")

    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    meals = meal_plan.meals.all() if meal_plan else []
    can_write = workspace.can_write(user) if workspace else True

    context = {
        "recipe": recipe,
        "meals": meals,
        "meal_plan": meal_plan,
        "workspace": workspace,
        "can_write": can_write,
    }
    return render(request, "recipes/partials/add_to_mealplan_modal.html", context)


@require_POST
def recipe_add_to_mealplan_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Add a recipe to a meal plan meal entry, creating a new meal if requested or needed.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to add recipes to meal plans.")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    shopping_list = get_active_list(request)

    meal_id = request.POST.get("meal_id", "").strip()
    meal_name = request.POST.get("meal_name", "").strip()
    scale_raw = request.POST.get("scale_factor", "1").strip()
    try:
        scale_factor = Decimal(scale_raw)
        if scale_factor <= Decimal("0"):
            scale_factor = Decimal("1.00")
    except Exception:
        scale_factor = Decimal("1.00")

    if meal_id and meal_id != "new":
        meal = get_object_or_404(Meal, id=meal_id, meal_plan=meal_plan)
    else:
        target_name = meal_name or f"{recipe.name} Dinner"
        meal = add_meal_to_plan(meal_plan, target_name)

    added_descriptions = add_recipe_to_meal(meal, recipe, shopping_list, request, scale_factor=scale_factor)

    scale_tag = f" ({scale_factor.normalize():f}x)" if scale_factor != Decimal("1.00") else ""
    toast_msg = f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name} and loaded {len(added_descriptions)} ingredients onto Shopping List"
    context = {
        "toast_message": toast_msg,
    }
    return render(request, "recipes/partials/toast_oob.html", context)
