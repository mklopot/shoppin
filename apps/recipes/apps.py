"""
Recipes application configuration.
"""

from django.apps import AppConfig


class RecipesConfig(AppConfig):
    """Configuration class for the recipes, ingredients, and rating models."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.recipes"
