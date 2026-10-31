"""
Management command to safely and idempotently import recipes from YAML (local or GitHub) into Django models.

Preserves referential integrity by never deleting existing recipes or altering existing ingredient IDs,
ensuring existing meal plans, shopping list attributions, ratings, and logs remain completely intact.
"""

from decimal import Decimal
import os
from pathlib import Path
import urllib.request
import yaml

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.core.categorizer import categorizer
from apps.core.utils import parse_amount_and_unit
from apps.recipes.models import Ingredient, Recipe

DEFAULT_GITHUB_RAW_URL = "https://raw.githubusercontent.com/mklopot/shoppin/main/shoppin/recipe-database.yaml"


class Command(BaseCommand):
    """Safely import recipes from YAML without modifying or corrupting existing relationships."""

    help = "Safely and idempotently import recipes from YAML (local file or GitHub) into the database."

    def add_arguments(self, parser):
        """Register command line arguments."""
        parser.add_argument(
            "--file",
            type=str,
            default="",
            help="Path to local YAML recipe database file",
        )
        parser.add_argument(
            "--url",
            type=str,
            default="",
            help="HTTP/HTTPS URL to fetch the recipe database YAML from",
        )
        parser.add_argument(
            "--from-github",
            action="store_true",
            help=f"Fetch latest recipe database directly from GitHub ({DEFAULT_GITHUB_RAW_URL})",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update description and directions for recipes that already exist (leaves ingredients untouched)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the import without writing any changes to the database",
        )

    def handle(self, *args, **options):
        """Execute the safe recipe import process."""
        yaml_content = ""
        source_desc = ""

        # 1. Determine recipe source
        if options["url"]:
            target_url = options["url"].strip()
            if not target_url.startswith(("http://", "https://")):
                self.stderr.write(self.style.ERROR(f"Invalid URL scheme in {target_url}. Only HTTP/HTTPS allowed."))
                return
            source_desc = f"URL {target_url}"
            self.stdout.write(f"Fetching recipes from {source_desc}...")
            req = urllib.request.Request(target_url, headers={"User-Agent": "Shoppin-RecipeImporter/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                yaml_content = resp.read().decode("utf-8")
        elif options["from_github"]:
            source_desc = f"GitHub ({DEFAULT_GITHUB_RAW_URL})"
            self.stdout.write(f"Fetching latest recipes from {source_desc}...")
            req = urllib.request.Request(DEFAULT_GITHUB_RAW_URL, headers={"User-Agent": "Shoppin-RecipeImporter/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                yaml_content = resp.read().decode("utf-8")
        elif options["file"]:
            target_path = Path(options["file"])
            if not target_path.exists():
                self.stderr.write(self.style.ERROR(f"Specified recipe file not found: {target_path}"))
                return
            source_desc = f"file {target_path}"
            self.stdout.write(f"Reading recipes from {source_desc}...")
            with open(target_path, "r", encoding="utf-8") as f:
                yaml_content = f.read()
        else:
            # Check default local locations
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
            default_legacy_file = base_dir / "legacy" / "recipe-database.yaml"
            if default_legacy_file.exists():
                source_desc = f"local file {default_legacy_file}"
                self.stdout.write(f"Reading recipes from {source_desc}...")
                with open(default_legacy_file, "r", encoding="utf-8") as f:
                    yaml_content = f.read()
            else:
                source_desc = f"GitHub fallback ({DEFAULT_GITHUB_RAW_URL})"
                self.stdout.write(f"Local legacy recipe file not found. Fetching from {source_desc}...")
                req = urllib.request.Request(DEFAULT_GITHUB_RAW_URL, headers={"User-Agent": "Shoppin-RecipeImporter/2.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                    yaml_content = resp.read().decode("utf-8")

        # 2. Parse YAML
        try:
            recipes_data = yaml.safe_load(yaml_content) or {}
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to parse YAML content: {e}"))
            return

        if not isinstance(recipes_data, dict):
            self.stderr.write(self.style.ERROR("Invalid recipe data format: root must be a dictionary of recipes."))
            return

        self.stdout.write(f"Parsed {len(recipes_data)} recipes from source.")

        dry_run = options["dry_run"]
        update_existing = options["update_existing"]

        # Cache existing recipes by normalized name and slug for fast lookup
        existing_recipes = {}
        existing_by_slug = {}
        for r in Recipe.objects.all():
            existing_recipes[r.name.strip().lower()] = r
            if r.slug:
                existing_by_slug[r.slug] = r

        created_recipes = 0
        created_ingredients = 0
        updated_recipes = 0
        skipped_recipes = 0

        with transaction.atomic():
            for recipe_name, details in recipes_data.items():
                if not recipe_name or not isinstance(details, dict):
                    continue

                clean_name = recipe_name.strip()
                norm_key = clean_name.lower()
                target_slug = slugify(clean_name)
                description = (details.get("description", "") or "").strip()
                directions = (details.get("directions", "") or "").strip()

                existing = existing_recipes.get(norm_key) or existing_by_slug.get(target_slug)

                if existing:
                    if update_existing:
                        if not dry_run:
                            changed = False
                            if description and existing.description != description:
                                existing.description = description
                                changed = True
                            if directions and existing.directions != directions:
                                existing.directions = directions
                                changed = True
                            if changed:
                                existing.save(update_fields=["description", "directions"])
                        updated_recipes += 1
                        self.stdout.write(f"  • Updated existing: {clean_name}")
                    else:
                        skipped_recipes += 1
                    continue

                # Brand new recipe to insert
                self.stdout.write(self.style.SUCCESS(f"  + Adding new recipe: {clean_name}"))
                created_recipes += 1

                recipe_obj = None
                if not dry_run:
                    recipe_obj = Recipe.objects.create(
                        name=clean_name,
                        description=description,
                        directions=directions,
                        is_public=True,
                        is_approved=True,
                    )
                    existing_recipes[norm_key] = recipe_obj
                    if recipe_obj.slug:
                        existing_by_slug[recipe_obj.slug] = recipe_obj

                raw_ingredients = details.get("ingredients") or []
                for order_idx, item in enumerate(raw_ingredients):
                    ing_name = ""
                    amount = Decimal("1.00")
                    amount_unit = ""
                    optional = False
                    brand = ""
                    vendor = ""

                    if isinstance(item, str):
                        ing_name = item.strip()
                    elif isinstance(item, dict):
                        for k, v in item.items():
                            ing_name = str(k).strip()
                            if isinstance(v, dict):
                                amt_raw = v.get("amount")
                                amount, amount_unit = parse_amount_and_unit(amt_raw)
                                optional = bool(v.get("optional", False))
                                brand = str(v.get("brand", "") or "").strip()
                                vendor = str(v.get("vendor", "") or "").strip()
                            break

                    if not ing_name:
                        continue

                    category = categorizer.get_category(ing_name)

                    if not dry_run and recipe_obj:
                        Ingredient.objects.create(
                            recipe=recipe_obj,
                            name=ing_name,
                            amount=amount,
                            amount_unit=amount_unit,
                            optional=optional,
                            brand=brand,
                            vendor=vendor,
                            category=category,
                            order=order_idx,
                        )
                    created_ingredients += 1

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[DRY RUN COMPLETE] Would create {created_recipes} new recipes ({created_ingredients} ingredients), "
                        f"update {updated_recipes}, and skip {skipped_recipes} existing."
                    )
                )
                # Rollback transaction in dry run
                transaction.set_rollback(True)
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n[SUCCESS] Successfully imported {created_recipes} new recipes ({created_ingredients} ingredients). "
                        f"Updated: {updated_recipes}, Left untouched: {skipped_recipes}."
                    )
                )
