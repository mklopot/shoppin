"""
Data migration to set Asian salad photo to the new high-resolution mandarin-forward photo asset.
"""

from django.db import migrations


def set_asian_salad_photo(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    recipe = Recipe.objects.filter(name="Asian salad").first()
    if not recipe:
        return

    recipe.photo_file = "recipes/photos/asian-salad.jpg"
    recipe.photo_urls = ["/media/recipes/photos/asian-salad.jpg"]
    recipe.save(update_fields=["photo_file", "photo_urls", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0010_update_asian_salad_photo"),
    ]

    operations = [
        migrations.RunPython(set_asian_salad_photo, migrations.RunPython.noop),
    ]
