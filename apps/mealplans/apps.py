"""
Meal plans application configuration.
"""

from django.apps import AppConfig


class MealplansConfig(AppConfig):
    """Configuration class for meal plan schedules, meals, and rules."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mealplans"
