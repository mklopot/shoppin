"""
Shopping application configuration.
"""

from django.apps import AppConfig


class ShoppingConfig(AppConfig):
    """Configuration class for the shopping list, stores, and items app."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shopping"
