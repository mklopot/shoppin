"""
Data migration to backfill is_web_imported=True for all recipes originating from external URLs,
and enforce that unverified web recipes are marked private (is_public=False) until copyright clearance.
"""

import re
from django.db import migrations

KNOWN_WEB_IMPORTED_SLUGS = {
    "giant-pumpkin-fondue-pudding-recipe-by-tasty",
    "noodles-with-lamb-sauce-laghman",
    "brisket-in-the-instant-pot",
    "lasagna",
    "lomo-saltado",
    "meatloaf-by-natasha",
    "peruvian-garlic-rice",
    "satsivi-georgian-chicken-in-walnut-sauce",
    "veggie-pot-pie",
    "kale-gnocchi",
    "mac-and-cheese-casserole",
}

URL_REGEX = re.compile(r"https?://[^\s]+|www\.[^\s]+")


def backfill_web_imported_recipes(apps, schema_editor):
    Recipe = apps.get_model("recipes", "Recipe")

    for recipe in Recipe.objects.all():
        dirs = recipe.directions or ""
        desc = recipe.description or ""
        bib_items = [str(x) for x in (recipe.bibliography or []) if not str(x).startswith("Photo:")]

        found_urls = URL_REGEX.findall(dirs) + URL_REGEX.findall(desc) + [u for b in bib_items for u in URL_REGEX.findall(b)]
        is_targeted = (recipe.slug in KNOWN_WEB_IMPORTED_SLUGS) or bool(found_urls)

        if not is_targeted:
            continue

        # Tag as web-imported
        recipe.is_web_imported = True

        # If copyright is not cleared, strictly unpublish from the public catalog
        if not recipe.copyright_cleared:
            recipe.is_public = False
            recipe.is_approved = False

        # Clean raw source URLs from the start of directions/descriptions and preserve in bibliography
        bib = list(recipe.bibliography or [])
        for url in found_urls:
            # Normalize url punctuation
            clean_url = url.rstrip('",;)>')
            if not any(clean_url in str(b) for b in bib):
                bib.append(clean_url)

        # If directions starts with a raw URL, strip the leading URL line
        clean_dirs = dirs
        if clean_dirs.strip().startswith(("http://", "https://")):
            lines = clean_dirs.splitlines()
            if lines and lines[0].strip().startswith(("http://", "https://")):
                clean_dirs = "\n".join(lines[1:]).strip()

        recipe.directions = clean_dirs
        recipe.bibliography = bib
        recipe.save(update_fields=["is_web_imported", "is_public", "is_approved", "directions", "bibliography"])


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0012_clean_asian_salad_bibliography"),
    ]

    operations = [
        migrations.RunPython(backfill_web_imported_recipes, migrations.RunPython.noop),
    ]
