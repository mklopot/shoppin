"""
Data migration to set Satsivi: Georgian Chicken in Walnut Sauce photo to the new
chicken-forward culinary photo asset and update updated_at for cache busting.
"""

from django.db import migrations


def set_satsivi_photo(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    recipe = Recipe.objects.filter(slug="satsivi-georgian-chicken-in-walnut-sauce").first()
    if not recipe:
        recipe = Recipe.objects.filter(name__icontains="Satsivi").first()
    if not recipe:
        return

    recipe.photo_file = "recipes/photos/satsivi-georgian-chicken-in-walnut-sauce.jpg"
    recipe.photo_urls = ["/media/recipes/photos/satsivi-georgian-chicken-in-walnut-sauce.jpg"]
    recipe.save(update_fields=["photo_file", "photo_urls", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0015_set_creamy_corn_casserole_photo"),
    ]

    operations = [
        migrations.RunPython(set_satsivi_photo, migrations.RunPython.noop),
    ]
