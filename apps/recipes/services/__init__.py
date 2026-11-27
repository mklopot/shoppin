"""
Recipes services package.
"""

from apps.recipes.services.ingredient_lint_service import (
    get_ingredient_unit_profiles,
    lint_ingredient,
    lint_recipe_ingredients,
)
from apps.recipes.services.nutrition_service import (
    calculate_ingredient_nutrition,
    calculate_recipe_nutrition,
    filter_recipes_by_nutrition,
    suggest_recipes_by_macro_goal,
    update_recipe_nutrition,
)
from apps.recipes.services.recipe_photo_ocr import extract_recipe_from_photos
from apps.recipes.services.recipe_scraper import (
    fetch_recipe_html,
    import_recipe_from_url,
    parse_ingredient_line,
    scrape_recipe_data,
)
from apps.recipes.services.recipe_service import (
    add_recipe_to_shopping_list,
    attach_recipe_made_counts,
    can_delete_user_recipe_photo,
    create_or_update_recipe,
    create_user_recipe_photo,
    delete_user_recipe_photo,
    get_complementary_recipe_candidates,
    get_filter_options,
    get_visible_serve_with_recipes,
    parse_tag_list,
    record_recipe_made,
    search_recipes,
    submit_recipe_rating,
)

__all__ = [
    "calculate_ingredient_nutrition",
    "calculate_recipe_nutrition",
    "filter_recipes_by_nutrition",
    "suggest_recipes_by_macro_goal",
    "update_recipe_nutrition",
    "extract_recipe_from_photos",
    "fetch_recipe_html",
    "import_recipe_from_url",
    "parse_ingredient_line",
    "scrape_recipe_data",
    "search_recipes",
    "get_complementary_recipe_candidates",
    "get_filter_options",
    "get_visible_serve_with_recipes",
    "parse_tag_list",
    "create_or_update_recipe",
    "create_user_recipe_photo",
    "can_delete_user_recipe_photo",
    "delete_user_recipe_photo",
    "submit_recipe_rating",
    "record_recipe_made",
    "add_recipe_to_shopping_list",
    "attach_recipe_made_counts",
    "get_ingredient_unit_profiles",
    "lint_ingredient",
    "lint_recipe_ingredients",
]
