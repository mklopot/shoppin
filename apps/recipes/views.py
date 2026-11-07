"""
Views for culinary recipes, interactive multi-facet search, detail, ratings, and creation.
"""

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
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
    fork_recipe,
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
    Supports multi-attribute including (+) and excluding (-) across all facets.
    """
    workspace = get_active_workspace(request)
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    can_write = workspace.can_write(user) if (is_authenticated and workspace) else False

    facet_keys = [
        "cuisine",
        "dish_type",
        "meal_type",
        "dietary",
        "occasion",
        "equipment",
        "difficulty",
    ]

    facet_labels = {
        "cuisine": "Cuisine",
        "dish_type": "Dish",
        "meal_type": "Meal",
        "dietary": "Diet",
        "occasion": "Occasion",
        "equipment": "Equipment",
        "difficulty": "Difficulty",
    }

    def _extract_facet_list(param_name: str) -> list[str]:
        raw_list = request.GET.getlist(param_name)
        items: list[str] = []
        for item in raw_list:
            for part in str(item).split(","):
                cleaned = part.strip()
                if cleaned and cleaned.lower() != "all" and cleaned not in items:
                    items.append(cleaned)
        return items

    includes: dict[str, list[str]] = {}
    excludes: dict[str, list[str]] = {}

    for facet in facet_keys:
        inc = _extract_facet_list(f"include_{facet}")
        # Legacy single/multi parameter compatibility (e.g. ?dish_type=Stew or ?cuisine=Italian)
        legacy = _extract_facet_list(facet)
        for item in legacy:
            if item not in inc:
                inc.append(item)

        exc = _extract_facet_list(f"exclude_{facet}")
        # Disallow simultaneous include & exclude of same value (exclusion wins)
        inc = [x for x in inc if x.lower() not in [e.lower() for e in exc]]

        includes[facet] = inc
        excludes[facet] = exc

    params: dict[str, Any] = {
        "q": request.GET.get("q", "").strip(),
        "sort": request.GET.get("sort", "name").strip(),
        "includes": includes,
        "excludes": excludes,
    }
    # Populate flat keys for legacy template and test references
    for facet in facet_keys:
        params[f"include_{facet}"] = includes[facet]
        params[f"exclude_{facet}"] = excludes[facet]
        params[facet] = includes[facet][0] if includes[facet] else ""

    recipes = search_recipes(params, user=user, workspace=workspace)
    filter_options = get_filter_options()
    meal_plan = get_active_meal_plan(request, workspace) if is_authenticated else None
    meals = meal_plan.meals.all() if meal_plan else []

    # Active filters list for chips rendering
    active_filters: list[dict[str, Any]] = []
    for facet in facet_keys:
        label = facet_labels.get(facet, facet.title())
        for val in includes[facet]:
            active_filters.append({
                "facet": facet,
                "facet_label": label,
                "value": val,
                "type": "include",
            })
        for val in excludes[facet]:
            active_filters.append({
                "facet": facet,
                "facet_label": label,
                "value": val,
                "type": "exclude",
            })

    active_filter_count = len(active_filters)

    def _format_options(opts: list[Any]) -> list[dict[str, str]]:
        res = []
        for o in opts:
            if isinstance(o, dict):
                res.append({"value": str(o.get("value", "")), "label": str(o.get("label", ""))})
            else:
                str_o = str(o)
                res.append({"value": str_o, "label": str_o.title() if str_o.islower() else str_o})
        return res

    facets_config = [
        {
            "key": "cuisine",
            "label": "Cuisine",
            "options": _format_options(filter_options["cuisines"]),
            "included": includes["cuisine"],
            "excluded": excludes["cuisine"],
        },
        {
            "key": "dish_type",
            "label": "Dish Type",
            "options": _format_options(filter_options["dish_types"]),
            "included": includes["dish_type"],
            "excluded": excludes["dish_type"],
        },
        {
            "key": "meal_type",
            "label": "Meal Type",
            "options": _format_options(filter_options["meal_types"]),
            "included": includes["meal_type"],
            "excluded": excludes["meal_type"],
        },
        {
            "key": "dietary",
            "label": "Dietary",
            "options": _format_options(filter_options["dietary_options"]),
            "included": includes["dietary"],
            "excluded": excludes["dietary"],
        },
        {
            "key": "occasion",
            "label": "Occasion",
            "options": _format_options(filter_options["occasions"]),
            "included": includes["occasion"],
            "excluded": excludes["occasion"],
        },
        {
            "key": "equipment",
            "label": "Equipment",
            "options": _format_options(filter_options["equipment_options"]),
            "included": includes["equipment"],
            "excluded": excludes["equipment"],
        },
        {
            "key": "difficulty",
            "label": "Difficulty",
            "options": _format_options(filter_options["difficulties"]),
            "included": includes["difficulty"],
            "excluded": excludes["difficulty"],
        },
    ]

    context: dict[str, Any] = {
        "workspace": workspace,
        "recipes": recipes,
        "recipe_count": recipes.count(),
        "filter_options": filter_options,
        "facets_config": facets_config,
        "params": params,
        "active_filters": active_filters,
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

    workspace = get_active_workspace(request)

    # Visibility & Moderation Access Control:
    # Public & approved recipes can be viewed by anyone without logging in.
    # Private or unapproved recipes require authentication and creator/moderator or shared workspace privileges.
    if not (recipe.is_public and recipe.is_approved):
        if not is_authenticated:
            messages.info(request, "This recipe is private or pending moderator approval. Please sign in to view it.")
            return redirect(f"{reverse('core:login')}?next={request.path}")
        is_creator = (recipe.created_by == user)
        is_staff = getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
        is_in_user_workspace = recipe.shared_workspaces.filter(
            Q(owner=user) | Q(memberships__user=user)
        ).exists()
        if not (is_creator or is_staff or is_in_user_workspace):
            return HttpResponseForbidden("This recipe is private or pending moderator approval.")

    shopping_list = get_active_list(request) if is_authenticated else None
    meal_plan = get_active_meal_plan(request, workspace) if is_authenticated else None

    can_write = workspace.can_write(user) if (is_authenticated and workspace) else False

    user_rating = None
    if is_authenticated:
        user_rating = RecipeRating.objects.filter(recipe=recipe, user=user).first()

    provenance_chain = recipe.get_provenance_chain()
    related_versions = recipe.get_related_workspace_versions(workspace) if workspace else Recipe.objects.none()
    is_in_current_workspace = recipe.shared_workspaces.filter(id=workspace.id).exists() if workspace else False
    is_owner = bool(is_authenticated and recipe.created_by == user)

    # Calculate who shared/copied it into this workspace
    sharer_display = ""
    if is_in_current_workspace:
        if recipe.last_shared_by:
            sharer_display = recipe.last_shared_by.get_full_name() or recipe.last_shared_by.username
        elif recipe.created_by:
            sharer_display = recipe.created_by.get_full_name() or recipe.created_by.username

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
        "provenance_chain": provenance_chain,
        "related_versions": related_versions,
        "is_in_current_workspace": is_in_current_workspace,
        "is_owner": is_owner,
        "sharer_display": sharer_display,
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

    dmca_profile = getattr(user, "dmca_profile", None)
    if dmca_profile and (dmca_profile.is_banned or dmca_profile.strikes >= 3):
        messages.error(
            request,
            "Your account has been restricted from creating or importing recipes due to repeated copyright infringement under our DMCA policy.",
        )
        return redirect("recipes:list")

    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        try:
            recipe = create_or_update_recipe(request.POST, files=request.FILES, user=user, workspace=workspace)
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
                is_public=False,
                is_approved=False,
                is_web_imported=True,
                copyright_cleared=False,
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
    raw_html = (request.POST.get("html") or "").strip() or None

    if not url:
        messages.error(request, "Please enter a valid recipe webpage URL.")
        return redirect("recipes:list")

    if action == "prefill":
        from urllib.parse import urlencode

        return redirect(f"{reverse('recipes:create')}?{urlencode({'import_url': url})}")

    try:
        recipe = import_recipe_from_url(url=url, user=user, html=raw_html)
        messages.success(request, f"Recipe '{recipe.name}' successfully imported!")
        return redirect(recipe.get_absolute_url())
    except ValueError as ve:
        messages.error(request, str(ve))
        return redirect("recipes:list")
    except Exception as exc:
        messages.error(request, f"Could not import recipe from '{url}': {exc}")
        return redirect("recipes:list")


@csrf_exempt
def recipe_bookmarklet_import_view(request: HttpRequest) -> HttpResponse:
    """
    Handle one-click bookmarklet imports from any external webpage.

    Accepts POST with 'url' and optionally 'html' captured directly by the user's browser,
    completely bypassing any anti-bot or paywall protections. Parses the recipe data
    and renders the recipe create form pre-filled for the user to review and confirm.
    """
    from urllib.parse import urlencode

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to save recipes to your collection.")
        # Preserve the recipe URL (and any inline JSON-LD payload) through login so the import resumes afterwards
        next_url = reverse("recipes:list")
        pending_url = (request.GET.get("url") or request.POST.get("url") or "").strip()
        pending_ld = (request.GET.get("ld") or "").strip()
        if pending_url:
            params = {"url": pending_url}
            if pending_ld:
                params["ld"] = pending_ld
            next_url = f"{reverse('recipes:import_bookmarklet')}?{urlencode(params)}"
        return redirect(f"{reverse('core:login')}?{urlencode({'next': next_url})}")

    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    if request.method == "POST":
        url = (request.POST.get("url") or "").strip()
        raw_html = (request.POST.get("html") or "").strip() or None
        if not url:
            messages.error(request, "No recipe webpage URL received from the bookmarklet.")
            return redirect("recipes:create")
    else:
        url = (request.GET.get("url") or "").strip()
        ld = (request.GET.get("ld") or "").strip()
        if not url:
            messages.error(request, "No recipe webpage URL received from the bookmarklet.")
            return redirect("recipes:create")
        if ld:
            raw_html = (
                f'<!DOCTYPE html><html><head><script type="application/ld+json">{ld}</script></head>'
                "<body></body></html>"
            )
        else:
            response = render(request, "recipes/bookmarklet_bridge.html", {"url": url})
            # The bridge tab is opened by the recipe site's tab and must keep its window.opener
            # link to receive the page HTML via postMessage. Django's default COOP of
            # 'same-origin' severs that link, so relax it for this response only.
            # SecurityMiddleware uses setdefault, so this value is preserved.
            response["Cross-Origin-Opener-Policy"] = "unsafe-none"
            return response

    try:
        data = scrape_recipe_data(url=url, html=raw_html)
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
            is_public=False,
            is_approved=False,
            is_web_imported=True,
            copyright_cleared=False,
        )
        ingredients = data["ingredients"]
        domain = data.get("domain") or "the webpage"
        messages.info(
            request,
            f"Pre-filled recipe from {domain} via bookmarklet! Review details below and click Save Recipe.",
        )
        filter_options = get_filter_options()
        all_recipes = Recipe.objects.all().order_by("name")
        context: dict[str, Any] = {
            "workspace": workspace,
            "filter_options": filter_options,
            "all_recipes": all_recipes,
            "recipe": recipe,
            "ingredients": ingredients,
            "import_url": url,
            "is_edit": False,
        }
        return render(request, "recipes/recipe_form.html", context)
    except Exception as exc:
        messages.error(request, f"Could not import recipe via bookmarklet: {exc}")
        return redirect(f"{reverse('recipes:create')}?import_url={url}")


def recipe_edit_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    Edit an existing recipe entry and ingredients.
    If the user does not own the recipe, creates a new forked version (copy-on-write).
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        messages.info(request, "Please sign in to edit recipes.")
        return redirect(f"{reverse('core:login')}?next={request.path}")

    dmca_profile = getattr(user, "dmca_profile", None)
    if dmca_profile and (dmca_profile.is_banned or dmca_profile.strikes >= 3):
        messages.error(
            request,
            "Your account has been restricted from editing recipes due to repeated copyright infringement under our DMCA policy.",
        )
        return redirect("recipes:list")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    workspace = get_active_workspace(request)
    if workspace and not workspace.can_write(user):
        return HttpResponseForbidden("You have read-only access to this workspace.")

    is_owner = (
        (recipe.created_by == user)
        or (recipe.created_by is None)
        or getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
    )

    if request.method == "POST":
        try:
            saved_recipe = create_or_update_recipe(
                request.POST,
                files=request.FILES,
                recipe_id=recipe.id,
                user=user,
                workspace=workspace,
            )
            if not is_owner:
                messages.success(
                    request,
                    f"Created your version '{saved_recipe.name}' (forked from '{recipe.name}')! "
                    f"Note: Recipes shared with a workspace or made public can be copied and modified by other members."
                )
            else:
                messages.success(request, f"Recipe '{saved_recipe.name}' updated successfully!")
            return redirect(saved_recipe.get_absolute_url())
        except ValidationError as ve:
            err_msg = getattr(ve, "message", None) or (ve.messages[0] if getattr(ve, "messages", None) else str(ve))
            messages.error(request, err_msg)

    filter_options = get_filter_options()
    all_recipes = Recipe.objects.exclude(id=recipe.id).order_by("name")

    user_display = (user.first_name or user.username) if user else "My"
    suggested_fork_name = f"{user_display}'s version of {recipe.name}"
    original_workspaces = recipe.shared_workspaces.all()

    context: dict[str, Any] = {
        "workspace": workspace,
        "recipe": recipe,
        "ingredients": recipe.ingredients.all(),
        "filter_options": filter_options,
        "all_recipes": all_recipes,
        "is_edit": True,
        "is_owner": is_owner,
        "is_fork_mode": not is_owner,
        "suggested_fork_name": suggested_fork_name,
        "original_workspaces": original_workspaces,
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
    is_in_workspace = recipe.shared_workspaces.filter(id=workspace.id).exists() if workspace else False

    context = {
        "recipe": recipe,
        "meals": meals,
        "meal_plan": meal_plan,
        "workspace": workspace,
        "can_write": can_write,
        "is_in_workspace": is_in_workspace,
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
    Enforces that recipes must be associated with the active workspace.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to add recipes to meal plans.")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    workspace = get_active_workspace(request)
    meal_plan = get_active_meal_plan(request, workspace)
    shopping_list = get_active_list(request)

    workspace_action = request.POST.get("workspace_action", "").strip().lower()
    if workspace and not recipe.shared_workspaces.filter(id=workspace.id).exists():
        if workspace_action == "copy" or request.POST.get("copy_to_workspace") in ("1", "true", "yes"):
            recipe = fork_recipe(recipe, user, target_workspaces=[workspace])
        elif workspace_action == "share" or request.POST.get("share_to_workspace") in ("1", "true", "yes"):
            recipe.shared_workspaces.add(workspace)
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])
        elif recipe.created_by == user or (not recipe.shared_workspaces.exists() and not recipe.is_public):
            recipe.shared_workspaces.add(workspace)
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])
        elif recipe.is_public:
            recipe.shared_workspaces.add(workspace)
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])
        else:
            context = {
                "toast_message": f"⚠️ Recipe '{recipe.name}' is not in workspace '{workspace.name}'. Please copy or share it with this workspace first.",
            }
            return render(request, "recipes/partials/toast_oob.html", context)

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

    try:
        added_descriptions = add_recipe_to_meal(meal, recipe, shopping_list, request, scale_factor=scale_factor)
    except ValidationError as ve:
        err_msg = getattr(ve, "message", None) or (ve.messages[0] if getattr(ve, "messages", None) else str(ve))
        context = {
            "toast_message": f"⚠️ {err_msg}",
        }
        return render(request, "recipes/partials/toast_oob.html", context)

    scale_tag = f" ({scale_factor.normalize():f}x)" if scale_factor != Decimal("1.00") else ""
    toast_msg = f"🥘 Added '{recipe.name}'{scale_tag} to {meal.name} and loaded {len(added_descriptions)} ingredients onto Shopping List"
    context = {
        "toast_message": toast_msg,
    }
    return render(request, "recipes/partials/toast_oob.html", context)


@require_POST
def recipe_copy_to_workspace_view(
    request: HttpRequest,
    recipe_id: int | None = None,
    slug: str | None = None,
) -> HttpResponse:
    """
    1-click copy/fork of an existing recipe into the active workspace.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return HttpResponseForbidden("Must be logged in to copy recipes.")

    workspace = get_active_workspace(request)
    if not workspace:
        messages.error(request, "No active workspace selected.")
        return redirect("recipes:list")

    recipe = _get_recipe_by_id_or_slug(recipe_id=recipe_id, slug=slug)
    forked = fork_recipe(recipe, user, target_workspaces=[workspace])
    messages.success(
        request,
        f"Copied '{forked.name}' into workspace '{workspace.name}'! "
        f"Note: Recipes shared with a workspace or made public can be copied and modified by other members."
    )
    return redirect(forked.get_absolute_url())
