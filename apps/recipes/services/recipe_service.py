"""
Service layer for recipe search, multi-faceted filtering, creation, and synchronization.
"""

from decimal import Decimal
from typing import Any

from django.db.models import Avg, F, Q, QuerySet
from django.http import HttpRequest

from apps.core.categorizer import categorizer
from apps.core.services.moderation_service import validate_content_clean
from apps.core.utils import (
    can_combine_units,
    clean_purpose,
    combine_amounts_and_units,
    parse_amount_and_unit,
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


def search_recipes(params: dict[str, Any], user: Any = None) -> QuerySet[Recipe]:
    """
    Search and filter recipes using multiple query parameters.

    Anonymous guests see publicly published and approved recipes. Authenticated
    users also see their own unpublished/pending recipes, while moderators (staff)
    can browse all recipes.

    Args:
        params: Dictionary containing filter options.
        user: Optional requesting user instance.

    Returns:
        Filtered and sorted QuerySet of Recipe objects.
    """
    if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with").all()
    elif user and user.is_authenticated:
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with").filter(
            Q(is_public=True, is_approved=True) | Q(created_by=user)
        )
    else:
        qs = Recipe.objects.prefetch_related("ingredients", "ratings", "serve_with").filter(
            is_public=True, is_approved=True
        )

    # 1. Free-text search
    q_str = str(params.get("q", "")).strip()
    if q_str:
        qs = qs.filter(
            Q(name__icontains=q_str)
            | Q(description__icontains=q_str)
            | Q(directions__icontains=q_str)
            | Q(cuisine__icontains=q_str)
            | Q(dish_type__icontains=q_str)
            | Q(ingredients__name__icontains=q_str)
        ).distinct()

    # 2. Cuisine filter
    cuisine = str(params.get("cuisine", "")).strip()
    if cuisine and cuisine.lower() != "all":
        qs = qs.filter(cuisine__iexact=cuisine)

    # 3. Dish type filter
    dish_type = str(params.get("dish_type", "")).strip()
    if dish_type and dish_type.lower() != "all":
        qs = qs.filter(dish_type__iexact=dish_type)

    # 4. Difficulty filter
    difficulty = str(params.get("difficulty", "")).strip()
    if difficulty and difficulty.lower() != "all":
        qs = qs.filter(difficulty_level__iexact=difficulty)

    # 5. Meal type filter (searches within JSON list or case-insensitive string)
    meal_type = str(params.get("meal_type", "")).strip()
    if meal_type and meal_type.lower() != "all":
        qs = qs.filter(
            Q(meal_type__icontains=meal_type)
        )

    # 6. Dietary restrictions filter
    dietary = str(params.get("dietary", "")).strip()
    if dietary and dietary.lower() != "all":
        qs = qs.filter(
            Q(dietary_restrictions__icontains=dietary)
        )

    # 7. Occasions filter
    occasion = str(params.get("occasion", "")).strip()
    if occasion and occasion.lower() != "all":
        qs = qs.filter(
            Q(occasions__icontains=occasion)
        )

    # 8. Special equipment filter
    equipment = str(params.get("equipment", "")).strip()
    if equipment and equipment.lower() != "all":
        qs = qs.filter(
            Q(special_equipment__icontains=equipment)
        )

    # 9. Sorting
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


def create_or_update_recipe(
    data: dict[str, Any],
    files: Any = None,
    recipe_id: int | None = None,
    user: Any = None,
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

    if recipe_id:
        recipe = Recipe.objects.get(id=recipe_id)
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

        if data.get("clear_photo") in ("1", "true", True):
            recipe.photo_file = None
        elif files and "photo_file" in files and files["photo_file"]:
            recipe.photo_file = files["photo_file"]

        recipe.save()
    else:
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
            photo_file=files.get("photo_file") if (files and "photo_file" in files) else None,
            created_by=user if user and user.is_authenticated else None,
        )

    # Process ingredients if provided in data
    if ingredient_names:
        recipe.ingredients.all().delete()
        for i, raw_ing_name in enumerate(ingredient_names):
            ing_name = str(raw_ing_name).strip()
            if not ing_name:
                continue

            raw_amt = ingredient_amounts[i] if i < len(ingredient_amounts) else "1"
            amount, parsed_unit = parse_amount_and_unit(raw_amt)
            unit = ingredient_units[i].strip() if i < len(ingredient_units) and ingredient_units[i] else parsed_unit
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
