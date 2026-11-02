from django.db import migrations

def backfill_recipe_provenance(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")
    for recipe in Recipe.objects.all():
        updated = False
        if not recipe.root_recipe_id:
            recipe.root_recipe = recipe
            updated = True
        if not recipe.original_created_at:
            recipe.original_created_at = recipe.created_at
            updated = True
        if not recipe.original_author_id and recipe.created_by_id:
            recipe.original_author = recipe.created_by
            user = recipe.created_by
            full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            recipe.original_author_name = full_name or getattr(user, 'username', '')
            updated = True
        if updated:
            recipe.save(update_fields=[
                "root_recipe",
                "original_created_at",
                "original_author",
                "original_author_name",
            ])

def reverse_backfill(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0005_recipe_forked_from_recipe_forked_from_author_name_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_recipe_provenance, reverse_backfill),
    ]
