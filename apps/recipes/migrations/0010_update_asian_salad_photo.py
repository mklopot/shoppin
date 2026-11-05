"""
Data migration to update Asian salad photo to a high-resolution, CC-licensed Wikimedia Commons photograph.
"""

from django.db import migrations

ASIAN_SALAD_PHOTO_URL = (
    "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/0b/Chinesechickensalad.jpg/"
    "1280px-Chinesechickensalad.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail"
)
ASIAN_SALAD_ATTRIBUTION = (
    "Photo: File:Chinesechickensalad.jpg by phototram, licensed under CC BY 2.0. "
    "Source: https://commons.wikimedia.org/wiki/File:Chinesechickensalad.jpg"
)


def update_asian_salad_photo(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    recipe = Recipe.objects.filter(name="Asian salad").first()
    if not recipe:
        return

    recipe.photo_urls = [ASIAN_SALAD_PHOTO_URL]
    recipe.photo_file = None

    bib = list(recipe.bibliography or [])
    if not any("Photo:" in str(entry) for entry in bib):
        bib.append(ASIAN_SALAD_ATTRIBUTION)
        recipe.bibliography = bib

    recipe.save(update_fields=["photo_urls", "photo_file", "bibliography"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0009_link_licensed_photos_for_missing_recipes"),
    ]

    operations = [
        migrations.RunPython(update_asian_salad_photo, migrations.RunPython.noop),
    ]
