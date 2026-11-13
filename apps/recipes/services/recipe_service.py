"""
Service layer for recipe search, multi-faceted filtering, creation, and synchronization.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Avg, Case, F, IntegerField, Q, QuerySet, Value, When
from django.http import HttpRequest

from apps.core.categorizer import categorizer
from apps.core.services.moderation_service import validate_content_clean
from apps.core.utils import (
    can_combine_units,
    clean_purpose,
    parse_amount_and_unit,
    parse_ingredient_line,
    singularize,
)
from apps.recipes.models import Ingredient, Recipe, RecipeMadeLog, RecipeRating
from apps.recipes.services.nutrition_service import update_recipe_nutrition
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem, ShoppingListItemSource
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.store_service import resolve_store_aisle, warm_store_aisles_async

POPULAR_CUISINES: list[str] = [
    "American",
    "Mexican",
    "Italian",
    "Chinese",
    "German",
    "Russian",
    "Korean",
    "French",
    "Indian",
    "Japanese",
    "Greek",
    "Spanish",
    "Thai",
    "Middle Eastern",
    "Eastern European",
]

POPULAR_DISH_TYPES: list[str] = [
    "Main",
    "Casserole",
    "Salad",
    "Stew",
    "Soup",
    "Sandwich",
    "Pasta",
    "Burger",
    "Side Dish",
    "Appetizer",
    "Dessert",
    "Bread",
    "Sauce",
]

POPULAR_DIETARY: list[str] = [
    "Vegetarian",
    "Vegan",
    "Dairy-Free",
    "Gluten-Free",
    "Kosher (Parve)",
    "Kosher (Dairy)",
    "Kosher (Meat)",
    "Nut-Free",
]

POPULAR_MEAL_TYPES: list[str] = [
    "Breakfast",
    "Lunch",
    "Dinner",
    "Snack",
    "Appetizer",
    "Dessert",
    "Side",
]

POPULAR_OCCASIONS: list[str] = [
    "Summer",
    "Winter",
    "Autumn",
    "Spring",
    "Christmas",
    "Thanksgiving",
    "New Year's",
    "Birthday",
    "Party / BBQ",
    "Weeknight Fast",
]

POPULAR_EQUIPMENT: list[str] = [
    "Instant Pot",
    "Casserole Dish",
    "Oven",
    "Wok",
    "Cast Iron Skillet",
    "Slow Cooker",
    "Blender",
    "Food Processor",
    "Steamer Basket",
    "Rolling Pin",
    "Grill",
]


def _normalize_filter_values(val: Any) -> list[str]:
    """Normalize input values into a cleaned list of non-empty strings (excluding 'all')."""
    if not val:
        return []
    items: list[str] = []
    if isinstance(val, str):
        for part in val.split(","):
            cleaned = part.strip()
            if cleaned and cleaned.lower() != "all" and cleaned not in items:
                items.append(cleaned)
    elif isinstance(val, (list, tuple, set)):
        for elem in val:
            if isinstance(elem, str):
                for part in elem.split(","):
                    cleaned = part.strip()
                    if cleaned and cleaned.lower() != "all" and cleaned not in items:
                        items.append(cleaned)
            elif elem is not None:
                cleaned = str(elem).strip()
                if cleaned and cleaned.lower() != "all" and cleaned not in items:
                    items.append(cleaned)
    return items


def search_recipes(
    params: dict[str, Any],
    user: Any = None,
    workspace: Any = None,
) -> QuerySet[Recipe]:
    """
    Search and filter recipes using multiple query parameters.
    Supports including and excluding multiple values per attribute.

    Anonymous guests see publicly published and approved recipes. Authenticated
    users also see their own unpublished/pending recipes and recipes shared to
    workspaces they are members of, while moderators (staff) can browse all recipes.

    Args:
        params: Dictionary containing filter options (e.g. q, sort,
                include_<facet>, exclude_<facet>, or legacy single <facet>).
        user: Optional requesting user instance.
        workspace: Optional active Workspace instance.

    Returns:
        Filtered and sorted QuerySet of Recipe objects.
    """
    if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with", "shared_workspaces").all()
    elif user and user.is_authenticated:
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with", "shared_workspaces").filter(
            Q(is_public=True, is_approved=True)
            | Q(created_by=user)
            | Q(shared_workspaces__owner=user)
            | Q(shared_workspaces__memberships__user=user)
        ).distinct()
    else:
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with", "shared_workspaces").filter(
            is_public=True, is_approved=True
        )

    if workspace and params.get("workspace_only") in ("1", "true", True):
        qs = qs.filter(shared_workspaces=workspace)

    # 1. Free-text search
    q_str = str(params.get("q", "")).strip().strip("'\"")
    if q_str:
        words = [w for w in q_str.split() if w]
        phrase_q = (
            Q(name__icontains=q_str)
            | Q(description__icontains=q_str)
            | Q(directions__icontains=q_str)
            | Q(cuisine__icontains=q_str)
            | Q(dish_type__icontains=q_str)
            | Q(ingredients__name__icontains=q_str)
        )
        if len(words) > 1:
            words_q = Q()
            for w in words:
                words_q &= (
                    Q(name__icontains=w)
                    | Q(description__icontains=w)
                    | Q(directions__icontains=w)
                    | Q(cuisine__icontains=w)
                    | Q(dish_type__icontains=w)
                    | Q(ingredients__name__icontains=w)
                )
            qs = qs.filter(phrase_q | words_q).distinct()
        else:
            qs = qs.filter(phrase_q).distinct()

        # Score relevance so matches in the recipe name appear at the top
        qs = qs.annotate(
            search_relevance=Case(
                When(name__iexact=q_str, then=Value(1)),
                When(name__istartswith=q_str, then=Value(2)),
                When(name__icontains=q_str, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        )

    # 2. Multi-facet filtering with Include (+) and Exclude (-)
    # Facet definitions: key -> (field_name, is_json_array)
    facets = {
        "cuisine": ("cuisine", False),
        "dish_type": ("dish_type", False),
        "difficulty": ("difficulty_level", False),
        "meal_type": ("meal_type", True),
        "dietary": ("dietary_restrictions", True),
        "occasion": ("occasions", True),
        "equipment": ("special_equipment", True),
    }

    includes_dict = params.get("includes", {}) if isinstance(params.get("includes"), dict) else {}
    excludes_dict = params.get("excludes", {}) if isinstance(params.get("excludes"), dict) else {}

    for facet, (field_name, is_json) in facets.items():
        # Collect included values from includes dict, include_<facet>, and legacy <facet>
        raw_inc = includes_dict.get(facet) or params.get(f"include_{facet}") or []
        inc_vals = _normalize_filter_values(raw_inc)
        if facet in params and not inc_vals:
            inc_vals = _normalize_filter_values(params.get(facet))

        # Collect excluded values
        raw_exc = excludes_dict.get(facet) or params.get(f"exclude_{facet}") or []
        exc_vals = _normalize_filter_values(raw_exc)

        # Avoid conflicts: exclusion takes precedence
        inc_vals = [v for v in inc_vals if v.lower() not in [x.lower() for x in exc_vals]]

        # Apply inclusions (OR logic within the facet: matching any included value)
        if inc_vals:
            facet_q = Q()
            for val in inc_vals:
                if is_json:
                    facet_q |= Q(**{f"{field_name}__icontains": val})
                else:
                    facet_q |= (Q(**{f"{field_name}__iexact": val}) | Q(**{f"{field_name}__icontains": val}))
            qs = qs.filter(facet_q)

        # Apply exclusions (AND NOT logic: must not contain any excluded value)
        for val in exc_vals:
            if is_json:
                qs = qs.filter(~Q(**{f"{field_name}__icontains": val}))
            else:
                qs = qs.filter(~Q(**{f"{field_name}__iexact": val}) & ~Q(**{f"{field_name}__icontains": val}))

    # 3. Sorting
    sort_key = str(params.get("sort", "name")).strip().lower()
    if sort_key == "rating":
        qs = qs.annotate(avg_stars=Avg("ratings__stars")).order_by("-avg_stars", "name")
    elif sort_key in ("time", "time_asc"):
        qs = qs.order_by("prep_time_minutes", "cook_time_minutes", "name")
    elif sort_key == "newest":
        qs = qs.order_by("-created_at")
    elif sort_key == "name_desc":
        qs = qs.order_by("-name")
    else:
        if q_str:
            qs = qs.order_by("search_relevance", "name")
        else:
            qs = qs.order_by("name")

    return qs


def get_filter_options() -> dict[str, list[str]]:
    """
    Retrieve aggregated filter options combining database values and standard tags.

    Returns:
        Dictionary of lists for cuisines, dish types, dietary restrictions,
        meal types, occasions, equipment, and difficulties.
    """
    # Extract distinct non-empty values from database
    db_cuisines = list(Recipe.objects.exclude(cuisine="").values_list("cuisine", flat=True).distinct())
    db_dish_types = list(Recipe.objects.exclude(dish_type="").values_list("dish_type", flat=True).distinct())

    cuisines = sorted(list(set(POPULAR_CUISINES + [c.title() for c in db_cuisines if c])))
    dish_types = sorted(list(set(POPULAR_DISH_TYPES + [d.title() for d in db_dish_types if d])))

    return {
        "cuisines": cuisines,
        "dish_types": dish_types,
        "dietary_options": POPULAR_DIETARY,
        "meal_types": POPULAR_MEAL_TYPES,
        "occasions": POPULAR_OCCASIONS,
        "equipment_options": POPULAR_EQUIPMENT,
        "difficulties": ["easy", "medium", "hard"],
    }


def parse_tag_list(raw_input: Any) -> list[str]:
    """Parse comma-separated strings, newline-separated strings, or list inputs into cleaned string list."""
    if not raw_input:
        return []
    if isinstance(raw_input, list):
        result: list[str] = []
        for elem in raw_input:
            if isinstance(elem, str):
                for line in elem.replace("\r", "").split("\n"):
                    for part in line.split(","):
                        cleaned = part.strip()
                        if cleaned and cleaned not in result:
                            result.append(cleaned)
            else:
                str_elem = str(elem).strip()
                if str_elem and str_elem not in result:
                    result.append(str_elem)
        return result
    if isinstance(raw_input, str):
        items: list[str] = []
        for line in raw_input.replace("\r", "").split("\n"):
            for part in line.split(","):
                cleaned = part.strip()
                if cleaned and cleaned not in items:
                    items.append(cleaned)
        return items
    return []


def generate_unique_recipe_name(base_name: str, exclude_id: int | None = None) -> str:
    """Generate a unique recipe name if base_name is already taken."""
    name = base_name.strip()
    qs = Recipe.objects.all()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    if not qs.filter(name__iexact=name).exists():
        return name
    counter = 2
    while qs.filter(name__iexact=f"{name} ({counter})").exists():
        counter += 1
    return f"{name} ({counter})"


def fork_recipe(
    source_recipe: Recipe,
    user: Any,
    target_workspaces: list[Any] | None = None,
    new_name: str | None = None,
    copy_ingredients: bool = True,
) -> Recipe:
    """
    Fork an existing recipe creating a new independent copy with full provenance links.
    """
    user_name = (user.first_name or user.username) if (user and user.is_authenticated) else "Someone"
    if not new_name:
        default_name = f"{user_name}'s version of {source_recipe.name}"
        new_name = generate_unique_recipe_name(default_name)
    else:
        new_name = generate_unique_recipe_name(new_name)

    root = source_recipe.root_recipe or source_recipe
    orig_author = source_recipe.original_author or source_recipe.created_by
    orig_author_name = source_recipe.original_author_display
    orig_created_at = source_recipe.original_date

    source_author_name = (
        (source_recipe.created_by.get_full_name() or source_recipe.created_by.username)
        if source_recipe.created_by
        else "Community Cook"
    )

    forked = Recipe.objects.create(
        name=new_name,
        description=source_recipe.description,
        directions=source_recipe.directions,
        cuisine=source_recipe.cuisine,
        dish_type=source_recipe.dish_type,
        difficulty_level=source_recipe.difficulty_level,
        portions=source_recipe.portions,
        prep_time_minutes=source_recipe.prep_time_minutes,
        cook_time_minutes=source_recipe.cook_time_minutes,
        storage_instructions=source_recipe.storage_instructions,
        reheating_instructions=source_recipe.reheating_instructions,
        dietary_restrictions=list(source_recipe.dietary_restrictions or []),
        meal_type=list(source_recipe.meal_type or []),
        occasions=list(source_recipe.occasions or []),
        special_equipment=list(source_recipe.special_equipment or []),
        bibliography=list(source_recipe.bibliography or []),
        photo_urls=list(source_recipe.photo_urls or []),
        photo_file=source_recipe.photo_file if source_recipe.photo_file else None,
        is_public=False,
        is_approved=False,
        is_web_imported=bool(source_recipe.is_web_imported),
        copyright_cleared=bool(source_recipe.copyright_cleared),
        created_by=user if (user and user.is_authenticated) else None,
        forked_from=source_recipe,
        forked_from_title=source_recipe.name,
        forked_from_author_name=source_author_name,
        root_recipe=root,
        original_author=orig_author,
        original_author_name=orig_author_name,
        original_created_at=orig_created_at,
        last_shared_by=user if (user and user.is_authenticated) else None,
    )

    if target_workspaces:
        for ws in target_workspaces:
            if ws:
                forked.shared_workspaces.add(ws)

    if copy_ingredients:
        for ing in source_recipe.ingredients.all():
            Ingredient.objects.create(
                recipe=forked,
                name=ing.name,
                amount=ing.amount,
                amount_unit=ing.amount_unit,
                optional=ing.optional,
                brand=ing.brand,
                vendor=ing.vendor,
                category=ing.category,
                order=ing.order,
            )

    return forked


def create_or_update_recipe(
    data: dict[str, Any],
    files: Any = None,
    recipe_id: int | None = None,
    user: Any = None,
    workspace: Any = None,
) -> Recipe:
    """
    Create a new recipe or update an existing one, parsing metadata, uploaded photos, and ingredients.

    Args:
        data: Request POST dictionary or mapping with recipe fields.
        files: Optional Request FILES mapping with uploaded files.
        recipe_id: Optional ID of recipe to update.
        user: Optional creating/editing user.

    Returns:
        The created or updated Recipe instance.
    """
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    directions = str(data.get("directions", "")).strip()
    cuisine = str(data.get("cuisine", "")).strip()
    dish_type = str(data.get("dish_type", "")).strip()
    difficulty = str(data.get("difficulty_level", "medium")).strip().lower()

    portions = int(data.get("portions", 4) or 4)
    prep_time = int(data.get("prep_time_minutes", 0) or 0)
    cook_time = int(data.get("cook_time_minutes", 0) or 0)

    storage_instructions = str(data.get("storage_instructions", "")).strip()
    reheating_instructions = str(data.get("reheating_instructions", "")).strip()

    dietary_restrictions = parse_tag_list(data.getlist("dietary_restrictions") if hasattr(data, "getlist") else data.get("dietary_restrictions"))
    meal_type = parse_tag_list(data.getlist("meal_type") if hasattr(data, "getlist") else data.get("meal_type"))
    occasions = parse_tag_list(data.getlist("occasions") if hasattr(data, "getlist") else data.get("occasions"))
    special_equipment = parse_tag_list(data.getlist("special_equipment") if hasattr(data, "getlist") else data.get("special_equipment"))
    bibliography = parse_tag_list(data.getlist("bibliography") if hasattr(data, "getlist") else data.get("bibliography"))

    photo_url = str(data.get("photo_url", "")).strip()
    photo_urls = [photo_url] if photo_url else parse_tag_list(data.getlist("photo_urls") if hasattr(data, "getlist") else data.get("photo_urls"))

    # Content Moderation: Prohibit expletives, obscenities, slurs, and hurtful language
    validate_content_clean(name, field_label="Recipe name")
    validate_content_clean(description, field_label="Recipe description")
    validate_content_clean(directions, field_label="Recipe directions")
    validate_content_clean(cuisine, field_label="Recipe cuisine")
    validate_content_clean(dish_type, field_label="Recipe dish type")
    validate_content_clean(storage_instructions, field_label="Storage instructions")
    validate_content_clean(reheating_instructions, field_label="Reheating instructions")

    # Pre-validate ingredient inputs
    ingredient_names = data.getlist("ingredient_name[]") if hasattr(data, "getlist") else data.get("ingredient_name[]", [])
    ingredient_amounts = data.getlist("ingredient_amount[]") if hasattr(data, "getlist") else data.get("ingredient_amount[]", [])
    ingredient_units = data.getlist("ingredient_unit[]") if hasattr(data, "getlist") else data.get("ingredient_unit[]", [])
    ingredient_optionals = data.getlist("ingredient_optional[]") if hasattr(data, "getlist") else data.get("ingredient_optional[]", [])
    ingredient_brands = data.getlist("ingredient_brand[]") if hasattr(data, "getlist") else data.get("ingredient_brand[]", [])
    ingredient_vendors = data.getlist("ingredient_vendor[]") if hasattr(data, "getlist") else data.get("ingredient_vendor[]", [])

    if ingredient_names:
        for raw_ing in ingredient_names:
            validate_content_clean(str(raw_ing), field_label="Ingredient name")
        for raw_brand in ingredient_brands:
            validate_content_clean(str(raw_brand), field_label="Ingredient brand")
        for raw_vendor in ingredient_vendors:
            validate_content_clean(str(raw_vendor), field_label="Ingredient vendor")

    # Visibility & Moderation status
    has_public_toggle = "has_public_toggle" in data or "is_public" in data
    if has_public_toggle:
        raw_public = data.get("is_public")
        if hasattr(data, "getlist"):
            vals = data.getlist("is_public")
            raw_public = vals[-1] if vals else raw_public
        is_public = str(raw_public).lower() in ("1", "true", "on", "yes")
    else:
        is_public = False

    existing_recipe: Recipe | None = None
    is_owner = True
    if recipe_id:
        existing_recipe = Recipe.objects.get(id=recipe_id)
        if user and user.is_authenticated:
            is_owner = (
                (existing_recipe.created_by_id == user.id)
                or (existing_recipe.created_by is None)
                or getattr(user, "is_superuser", False)
                or getattr(user, "is_staff", False)
            )
        else:
            is_owner = False

        if not is_owner:
            # Copy-on-write: Modifying a recipe you don't own creates a copy
            user_display = (user.first_name or user.username) if (user and user.is_authenticated) else "Someone"
            default_name = f"{user_display}'s version of {existing_recipe.name}"
            if not name or name == existing_recipe.name:
                name = generate_unique_recipe_name(default_name)
            else:
                name = generate_unique_recipe_name(name)

            root = existing_recipe.root_recipe or existing_recipe
            orig_author = existing_recipe.original_author or existing_recipe.created_by
            orig_author_name = existing_recipe.original_author_display
            orig_created_at = existing_recipe.original_date
            source_author = (
                (existing_recipe.created_by.get_full_name() or existing_recipe.created_by.username)
                if existing_recipe.created_by
                else "Community Cook"
            )

            recipe = Recipe.objects.create(
                name=name,
                description=description,
                directions=directions,
                cuisine=cuisine,
                dish_type=dish_type,
                difficulty_level=difficulty,
                portions=portions,
                prep_time_minutes=prep_time,
                cook_time_minutes=cook_time,
                storage_instructions=storage_instructions,
                reheating_instructions=reheating_instructions,
                dietary_restrictions=dietary_restrictions,
                meal_type=meal_type,
                occasions=occasions,
                special_equipment=special_equipment,
                bibliography=bibliography,
                photo_urls=photo_urls,
                photo_file=files.get("photo_file") if (files and "photo_file" in files) else existing_recipe.photo_file,
                is_public=False,
                is_approved=False,
                is_web_imported=bool(existing_recipe.is_web_imported),
                copyright_cleared=bool(existing_recipe.copyright_cleared),
                created_by=user if (user and user.is_authenticated) else None,
                forked_from=existing_recipe,
                forked_from_title=existing_recipe.name,
                forked_from_author_name=source_author,
                root_recipe=root,
                original_author=orig_author,
                original_author_name=orig_author_name,
                original_created_at=orig_created_at,
                last_shared_by=user if (user and user.is_authenticated) else None,
            )
        else:
            recipe = existing_recipe
            recipe.name = name
            recipe.description = description
            recipe.directions = directions
            recipe.cuisine = cuisine
            recipe.dish_type = dish_type
            recipe.difficulty_level = difficulty
            recipe.portions = portions
            recipe.prep_time_minutes = prep_time
            recipe.cook_time_minutes = cook_time
            recipe.storage_instructions = storage_instructions
            recipe.reheating_instructions = reheating_instructions
            recipe.dietary_restrictions = dietary_restrictions
            recipe.meal_type = meal_type
            recipe.occasions = occasions
            recipe.special_equipment = special_equipment
            recipe.bibliography = bibliography
            recipe.photo_urls = photo_urls

            raw_web_imported = data.get("is_web_imported")
            if str(raw_web_imported).lower() in ("1", "true", "yes") or bool(data.get("import_url")):
                recipe.is_web_imported = True

            is_staff_or_super = user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
            if is_staff_or_super and "copyright_cleared" in data:
                recipe.copyright_cleared = str(data.get("copyright_cleared")).lower() in ("1", "true", "yes", "on")

            if recipe.is_web_imported and not recipe.copyright_cleared:
                if has_public_toggle and is_public:
                    raise ValidationError(
                        "Web-imported recipes cannot be made public until verified as re-worded and non-infringing by an administrator."
                    )
                is_public = False
                recipe.is_public = False

            if has_public_toggle:
                recipe.is_public = is_public
                if not is_public:
                    recipe.is_approved = False
                elif is_public:
                    # If recipe was already approved, keep it approved!
                    # Only require moderation if it was previously NOT approved and user is non-staff
                    if not existing_recipe.is_approved and not is_staff_or_super:
                        recipe.is_approved = False
                    elif existing_recipe.is_approved:
                        recipe.is_approved = True

            if recipe.created_by is None and user and user.is_authenticated:
                recipe.created_by = user

            if data.get("clear_photo") in ("1", "true", True):
                recipe.photo_file = None
            elif files and "photo_file" in files and files["photo_file"]:
                recipe.photo_file = files["photo_file"]

            recipe.full_clean()
            recipe.save()
    else:
        is_staff_or_super = user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))

        raw_web_imported = data.get("is_web_imported")
        is_web_imported = str(raw_web_imported).lower() in ("1", "true", "yes") or bool(data.get("import_url"))

        copyright_cleared = False
        if is_staff_or_super and "copyright_cleared" in data:
            copyright_cleared = str(data.get("copyright_cleared")).lower() in ("1", "true", "yes", "on")

        if is_web_imported and not copyright_cleared:
            if has_public_toggle and is_public:
                raise ValidationError(
                    "Web-imported recipes cannot be made public until verified as re-worded and non-infringing by an administrator."
                )
            is_public = False

        if has_public_toggle:
            is_approved = is_public and (is_staff_or_super or user is None)
        else:
            is_approved = True

        recipe = Recipe(
            name=name,
            description=description,
            directions=directions,
            cuisine=cuisine,
            dish_type=dish_type,
            difficulty_level=difficulty,
            portions=portions,
            prep_time_minutes=prep_time,
            cook_time_minutes=cook_time,
            storage_instructions=storage_instructions,
            reheating_instructions=reheating_instructions,
            dietary_restrictions=dietary_restrictions,
            meal_type=meal_type,
            occasions=occasions,
            special_equipment=special_equipment,
            bibliography=bibliography,
            photo_urls=photo_urls,
            photo_file=files.get("photo_file") if (files and "photo_file" in files) else None,
            is_public=is_public,
            is_approved=is_approved,
            is_web_imported=is_web_imported,
            copyright_cleared=copyright_cleared,
            created_by=user if user and user.is_authenticated else None,
            last_shared_by=user if user and user.is_authenticated else None,
        )
        recipe.full_clean()
        recipe.save()

    # Process ingredients if provided in data
    if ingredient_names:
        recipe.ingredients.all().delete()
        for i, raw_ing_name in enumerate(ingredient_names):
            ing_name = str(raw_ing_name).strip()
            if not ing_name:
                continue

            raw_amt = ingredient_amounts[i] if i < len(ingredient_amounts) else "1"
            amount, parsed_unit = parse_amount_and_unit(raw_amt)
            unit = ingredient_units[i].strip() if (i < len(ingredient_units) and ingredient_units[i]) else parsed_unit

            # If user typed entire item & quantity into name (e.g. "2 cups all-purpose flour"), parse it
            if (not raw_amt or raw_amt == "1") and not unit:
                parsed_name, p_amt, p_unit = parse_ingredient_line(ing_name)
                if p_unit:
                    ing_name = parsed_name
                    amount = p_amt
                    unit = p_unit

            is_opt = (ingredient_optionals[i] == "1") if i < len(ingredient_optionals) else False
            brand = ingredient_brands[i].strip() if i < len(ingredient_brands) else ""
            vendor = ingredient_vendors[i].strip() if i < len(ingredient_vendors) else ""
            cat = categorizer.get_category(ing_name)

            Ingredient.objects.create(
                recipe=recipe,
                name=ing_name,
                amount=amount,
                amount_unit=unit,
                optional=is_opt,
                brand=brand,
                vendor=vendor,
                category=cat,
                order=i,
            )

    # Process serve_with relationships
    serve_with_ids = data.getlist("serve_with[]") if hasattr(data, "getlist") else data.get("serve_with[]", [])
    if serve_with_ids:
        recipe.serve_with.set(Recipe.objects.filter(id__in=serve_with_ids))

    # Workspace Association & Sharing Destinations
    sharing_dest = str(data.get("sharing_destination", "")).strip().lower()
    if sharing_dest == "private":
        recipe.shared_workspaces.clear()
    elif sharing_dest == "original" and existing_recipe:
        recipe.shared_workspaces.set(existing_recipe.shared_workspaces.all())
        if user and user.is_authenticated:
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])
    elif sharing_dest == "both" and existing_recipe:
        workspaces_to_add = set(existing_recipe.shared_workspaces.all())
        if workspace:
            workspaces_to_add.add(workspace)
        recipe.shared_workspaces.set(workspaces_to_add)
        if user and user.is_authenticated:
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])
    elif sharing_dest in ("current", "workspace", "active_workspace"):
        if workspace:
            recipe.shared_workspaces.set([workspace])
            if user and user.is_authenticated:
                recipe.last_shared_by = user
                recipe.save(update_fields=["last_shared_by"])
    elif "share_workspaces" in data:
        ws_ids = data.getlist("share_workspaces") if hasattr(data, "getlist") else data.get("share_workspaces")
        if ws_ids:
            recipe.shared_workspaces.set(ws_ids)
            if user and user.is_authenticated:
                recipe.last_shared_by = user
                recipe.save(update_fields=["last_shared_by"])
    elif workspace and (not recipe_id or not is_owner):
        # Default association for newly created recipes or newly created forks in workspace context
        recipe.shared_workspaces.add(workspace)
        if user and user.is_authenticated:
            recipe.last_shared_by = user
            recipe.save(update_fields=["last_shared_by"])

    # Recalculate nutritional analysis for the updated ingredients and portions
    try:
        update_recipe_nutrition(recipe, save=True)
    except Exception:
        pass

    return recipe


def submit_recipe_rating(recipe: Recipe, user: Any, stars: int, thumbs_up: bool) -> RecipeRating:
    """Submit or update a user rating/endorsement for a recipe."""
    rating, _ = RecipeRating.objects.update_or_create(
        recipe=recipe,
        user=user,
        defaults={
            "stars": max(1, min(5, stars)),
            "thumbs_up": thumbs_up,
        },
    )
    return rating


def record_recipe_made(
    recipe: Recipe,
    user: Any = None,
    notes: str = "",
) -> RecipeMadeLog | None:
    """
    Increment times_made counter on a recipe and record a RecipeMadeLog entry.

    Args:
        recipe: Target Recipe.
        user: Optional User who prepared the dish.
        notes: Optional preparation notes or remarks.

    Returns:
        The created RecipeMadeLog instance if user is authenticated, else None.
    """
    Recipe.objects.filter(id=recipe.id).update(times_made=F("times_made") + 1)
    recipe.refresh_from_db(fields=["times_made"])

    if user and getattr(user, "is_authenticated", False):
        return RecipeMadeLog.objects.create(recipe=recipe, user=user, notes=notes)
    return None


def add_recipe_to_shopping_list(
    recipe: Recipe,
    shopping_list: ShoppingList,
    request: HttpRequest | None = None,
) -> list[str]:
    """
    Load all recipe ingredients onto the active shopping list with attribution,
    combining amounts for identical ingredients and resetting locked state.

    Args:
        recipe: Target Recipe.
        shopping_list: Active ShoppingList.
        request: Optional HttpRequest for WebSocket attribution.

    Returns:
        List of added ingredient descriptions.
    """
    added_descriptions: list[str] = []
    actor_name = request.user.username if (request and request.user.is_authenticated) else "unknown"
    sender_id = request.headers.get("X-Client-Id") if request else ""
    recipe_purpose_name = clean_purpose(recipe.name)

    for ingredient in recipe.ingredients.all():
        normalized_name = singularize(ingredient.name.lower())
        brand = ingredient.brand or ""
        unit = ingredient.amount_unit or ""

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
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name} (combined)")
        else:
            cat = ingredient.category or categorizer.get_category(ingredient.name)
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
                source_recipe=recipe,
                source_ingredient=ingredient,
                locked=False,
            )
            added_descriptions.append(f"{amount_fmt}{unit_str} {ingredient.name}".strip())

        ShoppingListItemSource.objects.create(
            item=target_item,
            recipe=recipe,
            ingredient=ingredient,
            amount=ingredient.amount,
            amount_unit=ingredient.amount_unit,
            purpose=recipe_purpose_name,
        )
        target_item.recalculate_from_attributions()

    # Warm missing aisles in background so user response returns immediately
    if shopping_list.active_store:
        warm_store_aisles_async(shopping_list)

    # Broadcast WebSocket update
    broadcast_messages = [f"🥘 Added '{recipe.name}' to shopping list"]
    for desc in added_descriptions[:5]:
        broadcast_messages.append(f"🛒 Added {desc} to shopping list")
    if len(added_descriptions) > 5:
        broadcast_messages.append(f"🛒 ...and {len(added_descriptions) - 5} more ingredients")

    broadcast_shopping_list_update(
        shopping_list=shopping_list,
        toast_message=f"Added '{recipe.name}' ingredients to shopping list",
        toast_messages=broadcast_messages,
        actor_name=actor_name,
        sender_client_id=sender_id,
    )

    return added_descriptions


def get_featured_carousel_recipes(limit: int = 10) -> list[Recipe]:
    """
    Retrieve public, approved recipes that have valid photos for display in carousels.

    Prioritizes recipes with photos, descriptions, and ratings.

    Args:
        limit: Maximum number of recipes to return.

    Returns:
        List of Recipe instances.
    """
    qs = (
        Recipe.objects.filter(is_public=True, is_approved=True)
        .exclude(photo_file="", photo_urls=[])
        .annotate(avg_stars=Avg("ratings__stars"))
    )

    candidates = list(qs)
    recipes_with_photos = [r for r in candidates if r.primary_photo_url]

    recipes_with_photos.sort(
        key=lambda r: (
            1 if r.description else 0,
            float(r.avg_stars or 0),
            r.times_made,
        ),
        reverse=True,
    )
    return recipes_with_photos[:limit]

