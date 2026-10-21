from decimal import Decimal
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.categorizer import categorizer
from apps.core.utils import parse_amount_and_unit
from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem


class Command(BaseCommand):
    help = "Import recipes and preset lists from legacy YAML files into the SQLite/Postgres database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Clear existing recipes and preset lists before importing",
        )

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
        legacy_dir = base_dir / "legacy"
        recipe_file = legacy_dir / "recipe-database.yaml"
        lists_dir = legacy_dir / "lists"

        if not recipe_file.exists():
            self.stderr.write(self.style.ERROR(f"Recipe database not found at {recipe_file}"))
            return

        with transaction.atomic():
            if options["overwrite"]:
                self.stdout.write("Overwriting existing data...")
                Recipe.objects.all().delete()
                ShoppingList.objects.filter(is_preset=True).delete()

            # 1. Import Recipes
            self.stdout.write(f"Loading recipes from {recipe_file}...")
            with open(recipe_file, encoding="utf-8") as f:
                recipes_data = yaml.safe_load(f) or {}

            recipe_count = 0
            ingredient_count = 0

            for recipe_name, details in recipes_data.items():
                if not recipe_name or not isinstance(details, dict):
                    continue

                description = details.get("description", "") or ""
                directions = details.get("directions", "") or ""

                recipe, _ = Recipe.objects.update_or_create(
                    name=recipe_name.strip(),
                    defaults={
                        "description": description.strip(),
                        "directions": directions.strip(),
                        "is_public": True,
                        "is_approved": True,
                    },
                )
                recipe_count += 1

                # Clean out existing ingredients if re-importing
                recipe.ingredients.all().delete()

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
                        # Key is ingredient name, value is dict of attributes
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

                    Ingredient.objects.create(
                        recipe=recipe,
                        name=ing_name,
                        amount=amount,
                        amount_unit=amount_unit,
                        optional=optional,
                        brand=brand,
                        vendor=vendor,
                        category=category,
                        order=order_idx,
                    )
                    ingredient_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully imported {recipe_count} recipes and {ingredient_count} ingredients."
                )
            )

            # 2. Import Preset Lists
            if lists_dir.exists():
                self.stdout.write(f"Loading preset lists from {lists_dir}...")
                preset_list_count = 0
                preset_item_count = 0

                for yaml_path in sorted(lists_dir.glob("*.yaml")):
                    clean_title = yaml_path.stem.replace("_", " ").title()
                    if clean_title == "Ezras Lunches":
                        clean_title = "Ezra's Lunches"
                    elif clean_title == "Ians Lunches":
                        clean_title = "Ian's Lunches"
                    elif clean_title == "Beth Work Lunches":
                        clean_title = "Beth's Work Lunches"

                    shopping_list, _ = ShoppingList.objects.update_or_create(
                        name=clean_title,
                        is_preset=True,
                    )
                    shopping_list.items.all().delete()
                    preset_list_count += 1

                    with open(yaml_path, encoding="utf-8") as f:
                        items_data = yaml.safe_load(f) or []

                    for order_idx, item in enumerate(items_data):
                        item_name = ""
                        amount = Decimal("1.00")
                        amount_unit = ""
                        optional = False
                        brand = ""
                        vendor = ""

                        if isinstance(item, str):
                            item_name = item.strip()
                        elif isinstance(item, dict):
                            for k, v in item.items():
                                item_name = str(k).strip()
                                if isinstance(v, dict):
                                    amt_raw = v.get("amount")
                                    amount, amount_unit = parse_amount_and_unit(amt_raw)
                                    optional = bool(v.get("optional", False))
                                    brand = str(v.get("brand", "") or "").strip()
                                    vendor = str(v.get("vendor", "") or "").strip()
                                break

                        if not item_name:
                            continue

                        category = categorizer.get_category(item_name)

                        ShoppingListItem.objects.create(
                            shopping_list=shopping_list,
                            name=item_name,
                            amount=amount,
                            amount_unit=amount_unit,
                            brand=brand,
                            vendor=vendor,
                            category=category,
                            optional=optional,
                            status=ItemStatus.NEED,
                            order=order_idx,
                        )
                        preset_item_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully imported {preset_list_count} preset lists and {preset_item_count} items."
                    )
                )

            # 3. Ensure a default active Main Shopping List exists
            main_list, created = ShoppingList.objects.get_or_create(
                name="Main Shopping List",
                is_preset=False,
            )
            if created:
                self.stdout.write("Created default 'Main Shopping List'.")
