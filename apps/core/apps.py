"""
Core application configuration.
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration class for the shared core utilities and categorizer."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        """Register application signals for content moderation."""
        import apps.core.signals  # noqa: F401
