from django.db import migrations

MONTE_CHRISTO_DIRECTIONS = (
    "Prep the bread: Spread the mustard evenly across one side of each slice of bread.\n"
    "Assemble the double-decker sandwich: Place the first bread slice mustard-side up. Layer on one slice of Swiss cheese and half of the sliced ham. Add the second slice of bread, then layer the remaining ham and the second slice of Swiss cheese. Cap with the third slice of bread (mustard-side down) and press down gently to compact.\n"
    "Whisk the egg: In a shallow, wide bowl or pie dish, thoroughly beat the egg.\n"
    "Heat the skillet: Melt the butter in a skillet or nonstick frying pan over medium-low heat.\n"
    "Coat the sandwich: Dip the assembled sandwich into the beaten egg, turning to coat both sides and all edges evenly.\n"
    "Pan-fry to golden: Place the coated sandwich in the skillet. Cook for 3 to 4 minutes per side until crisp and golden brown, pressing down gently with a spatula so the cheese melts through the layers (cover briefly with a lid if needed to accelerate melting).\n"
    "Slice and serve: Transfer to a cutting board, slice in half diagonally, and serve warm."
)


def apply_directions(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    monte = Recipe.objects.filter(slug="monte-christo-sandwich").first()
    if not monte:
        monte = Recipe.objects.filter(name__iexact="Monte Christo Sandwich").first()
    if monte:
        monte.directions = MONTE_CHRISTO_DIRECTIONS
        monte.save(update_fields=["directions"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0013_backfill_web_imported_recipes"),
    ]

    operations = [
        migrations.RunPython(apply_directions, migrations.RunPython.noop),
    ]
