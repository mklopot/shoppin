from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError
import fcntl
import logging

from util import parse_amount
import shopping

logger = logging.getLogger("shoppin.recipes")
logger.addHandler(logging.NullHandler())

@dataclass
class Recipe:
    name: str
    ingredients: list["Ingredient"]
    directions: str = ""
    description: str = ""

    def make_shopping_plan(self):
        return self.ingredients


class Ingredient:
    def __init__(self, name="", attribution=None, purpose="", amount=1, amount_unit="", optional=False, brand="", vendor="", item=None):
        self.name = name
        self.attribution = attribution
        self.purpose = purpose
        self.amount = amount
        self.amount_unit = amount_unit
        self.optional = optional
        self.brand = brand
        self.vendor = vendor
        self.item = item
 

class Recipes:
    def __init__(self, recipes: list[Recipe] = {}) -> None:
        logger.debug(f"Instantiated a recipe database {self}")
        self.recipes = recipes

    def save(self, recipe_db_filepath="recipe-database.yaml"):
        logger.debug(f"Saving recipe database to {recipe_db_filepath}")
        with open(recipe_db_filepath, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            for recipe in self.recipes:
                f.write(f"{recipe}:\n")
                if self.recipes[recipe].description:
                    f.write("  description: |\n")
                    description = "    " + "\n    ".join(self.recipes[recipe].description.split("\n"))
                    f.write(description + "\n")
                if self.recipes[recipe].directions:
                    f.write("  directions: |\n")
                    directions = "    " + "\n    ".join(self.recipes[recipe].directions.split("\n"))
                    f.write(directions + "\n")
                if self.recipes[recipe].ingredients:
                    f.write("  ingredients:\n")
                    for ingredient in self.recipes[recipe].ingredients:
                        if ingredient.optional is False and \
                                ingredient.amount == 1 and not \
                                ingredient.amount_unit and not \
                                ingredient.brand and not \
                                ingredient.vendor:
                            f.write(f"    - {ingredient.name}\n")
                        else:
                            f.write(f"    - {ingredient.name}:\n")
                            if ingredient.amount != 1 or ingredient.amount_unit:
                                f.write(f"        amount: {ingredient.amount:.2g}")
                                if ingredient.amount_unit:
                                    f.write(f" {ingredient.amount_unit}")
                                f.write("\n")
                        if ingredient.optional:
                            f.write("        optional: True\n")
                        if ingredient.brand:
                            f.write(f"        brand: {ingredient.brand}\n")
                        if ingredient.vendor:
                            f.write(f"        vendor: {ingredient.vendor}\n")
                        f.write("\n")
                f.write("\n")
            fcntl.flock(f, fcntl.LOCK_UN)

    def load(self, recipe_db_filepath="recipe-database.yaml"):
        logger.debug(f"Loading recipe database from {recipe_db_filepath}")
        with open(recipe_db_filepath) as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                loaded_recipes = yaml.safe_load(f)
            except ScannerError as e:
                logger.warning(f"Could not parse recipe database from file {recipe_db_filepath}:\n{e}")
            fcntl.flock(f, fcntl.LOCK_UN)
        for loaded_recipe in loaded_recipes:
            ingredients = []
            directions = loaded_recipes[loaded_recipe].get("directions", "")
            description = loaded_recipes[loaded_recipe].get("description", "")
            loaded_ingredients = loaded_recipes[loaded_recipe].get("ingredients", [])
            self.recipes[loaded_recipe] = (Recipe(name=loaded_recipe,
                                                  ingredients=[],
                                                  directions=directions,
                                                  description=description))
            for ingredient in loaded_ingredients:
                if type(ingredient) is str:
                    ingredients.append(Ingredient(name=ingredient,
                        purpose=self.recipes[loaded_recipe].name,
                        attribution=self.recipes[loaded_recipe]))
                else:
                    name = list(ingredient.keys())[0].strip()
                    amount_with_unit = str(ingredient[name].get("amount", "1"))
                    amount, amount_unit = parse_amount(amount_with_unit)
                    amount_unit = amount_unit.strip()
                    optional = ingredient[name].get("optional", False)
                    brand = ingredient[name].get("brand", "").strip()
                    vendor = ingredient[name].get("vendor", "").strip()
                    ingredients.append(Ingredient(name=name,
                                                  amount=amount,
                                                  amount_unit=amount_unit,
                                                  optional=optional,
                                                  brand=brand,
                                                  vendor=vendor,
                                                  purpose=self.recipes[loaded_recipe].name,
                                                  attribution=self.recipes[loaded_recipe]))

            self.recipes[loaded_recipe].ingredients = ingredients
