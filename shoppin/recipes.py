from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError


from util import parse_amount
import shopping


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
        self.recipes = recipes

    def load(self, recipe_db_filepath="recipe-database.yaml"):
        with open(recipe_db_filepath) as f:
            try:
                loaded_recipes = yaml.safe_load(f)
            except ScannerError as e:
                print("Could not parse recipe database from file", recipe_db_filepath, ":\n", e)
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
