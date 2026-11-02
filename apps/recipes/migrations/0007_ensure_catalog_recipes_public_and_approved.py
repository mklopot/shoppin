from django.db import migrations


def make_catalog_recipes_public(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    # 1. Ensure core catalog recipes (including stuffed-shells and stir-fry) are public and approved
    Recipe.objects.filter(slug__in=["stuffed-shells", "stir-fry"]).update(
        is_public=True,
        is_approved=True,
    )
    # 2. Ensure all baseline system/legacy recipes created without a specific user are public & approved
    Recipe.objects.filter(created_by__isnull=True).update(
        is_public=True,
        is_approved=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0006_backfill_recipe_provenance"),
    ]

    operations = [
        migrations.RunPython(make_catalog_recipes_public, migrations.RunPython.noop),
    ]
