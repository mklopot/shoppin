"""
Data migration to set Creamy Corn Casserole photo to the new golden-baked casserole photo asset
and update updated_at for browser/CDN cache busting.
"""

from django.db import migrations


def set_creamy_corn_casserole_photo(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    recipe = Recipe.objects.filter(slug="creamy-corn-casserole").first()
    if not recipe:
        recipe = Recipe.objects.filter(name="Creamy Corn Casserole").first()
    if not recipe:
        return

    recipe.photo_file = "recipes/photos/creamy-corn-casserole.jpg"
    recipe.photo_urls = ["/media/recipes/photos/creamy-corn-casserole.jpg"]
    recipe.save(update_fields=["photo_file", "photo_urls", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0014_backfill_monte_christo_directions"),
    ]

    operations = [
        migrations.RunPython(set_creamy_corn_casserole_photo, migrations.RunPython.noop),
    ]
