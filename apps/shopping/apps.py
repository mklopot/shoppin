"""
Shopping application configuration.
"""

from django.apps import AppConfig


class ShoppingConfig(AppConfig):
    """Configuration class for the shopping list, stores, and items app."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shopping"

    def ready(self) -> None:
        """Initialize background scheduler for automated preset refreshes."""
        import os
        import sys

        # Skip starting background scheduler during tests, migrations, and CLI utilities
        is_testing = (
            "test" in sys.argv
            or any("pytest" in arg for arg in sys.argv)
            or bool(os.environ.get("PYTEST_CURRENT_TEST"))
        )
        if is_testing:
            return

        skip_commands = {
            "makemigrations",
            "migrate",
            "collectstatic",
            "shell",
            "createsuperuser",
            "run_preset_schedules",
        }
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        # For runserver, ensure we only run in the actual worker process (RUN_MAIN == 'true')
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return

        from apps.shopping.services.scheduler import start_preset_scheduler
        start_preset_scheduler(poll_interval=5)
