"""
Management command to run due preset list schedules across all workspaces.

Usage:
    python manage.py run_preset_schedules
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.shopping.models import ShoppingList
from apps.shopping.services.preset_service import apply_preset_scheduled_refresh


class Command(BaseCommand):
    help = "Execute scheduled refreshes for all preset lists that are due."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force apply all enabled preset schedules regardless of due date",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        force = options.get("force", False)

        qs = ShoppingList.objects.filter(is_preset=True, is_schedule_enabled=True)
        if not force:
            qs = qs.filter(next_occurrence__isnull=False, next_occurrence__lte=now)

        due_presets = list(qs)
        self.stdout.write(f"Found {len(due_presets)} preset list(s) to refresh.")

        applied_count = 0
        for preset in due_presets:
            try:
                res = apply_preset_scheduled_refresh(preset)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Refreshed '{preset.name}': removed {res['removed_count']} items, "
                        f"re-added {res['added_count']} items. Next run at: {res['next_occurrence']}"
                    )
                )
                applied_count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to refresh preset '{preset.name}': {e}")
                )

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {applied_count} preset list(s)."))
