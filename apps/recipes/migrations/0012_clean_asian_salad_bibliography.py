"""
Data migration to remove obsolete Wikimedia Commons photo attribution from Asian salad bibliography.
"""

from django.db import migrations


def clean_asian_salad_bibliography(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    recipe = Recipe.objects.filter(name="Asian salad").first()
    if not recipe:
        return

    old_bib = list(recipe.bibliography or [])
    new_bib = [item for item in old_bib if "Chinesechickensalad.jpg" not in str(item)]
    recipe.bibliography = new_bib
    recipe.save(update_fields=["bibliography"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0011_set_gourmet_asian_salad_photo"),
    ]

    operations = [
        migrations.RunPython(clean_asian_salad_bibliography, migrations.RunPython.noop),
    ]
