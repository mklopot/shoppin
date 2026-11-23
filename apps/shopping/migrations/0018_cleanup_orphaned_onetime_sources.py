"""Data migration clearing stale legacy source links on unattributed one-time items."""

from django.db import migrations, models


def clear_orphaned_onetime_sources(apps, schema_editor):
    """Clear stale legacy source FKs on unattributed items marked as one-time purchase."""
    ShoppingListItem = apps.get_model("shopping", "ShoppingListItem")
    ShoppingListItemSource = apps.get_model("shopping", "ShoppingListItemSource")

    attributed_item_ids = ShoppingListItemSource.objects.values_list("item_id", flat=True)
    (
        ShoppingListItem.objects.exclude(id__in=attributed_item_ids)
        .filter(
            models.Q(purpose__iexact="one-time purchase")
            | models.Q(purpose__iexact="for one-time purchase")
        )
        .filter(
            models.Q(source_recipe__isnull=False)
            | models.Q(source_meal__isnull=False)
            | models.Q(source_ingredient__isnull=False)
            | models.Q(source_preset__isnull=False)
        )
        .update(
            source_recipe=None,
            source_meal=None,
            source_ingredient=None,
            source_preset=None,
        )
    )


def noop_reverse(apps, schema_editor):
    """Reverse no-op for idempotent cleanup migration."""


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0017_alter_shoppinglistitem_purpose_and_more"),
    ]

    operations = [
        migrations.RunPython(clear_orphaned_onetime_sources, noop_reverse),
    ]
