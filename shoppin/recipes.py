from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError


from util import parse_amount

@dataclass
class Ingredient:
    name: str
    amount: float = 1
    amount_unit: str = ""
    optional: bool = False
    brand: str = ""
    vendor: str = ""
    

@dataclass
class Recipe:
    name: str
    ingredients: list[Ingredient]
    directions: str = ""
    description: str = ""

class Recipes:
    def __init__(self, recipes: list[Recipe] = {}) -> None:
        self.recipes = recipes

    def load(self, recipe_db_filepath="recipe-database.yaml"):
        with open(recipe_db_filepath) as f:
            try:
                loaded_recipes = yaml.load(f)
            except ScannerError:
                print("Could not parse recipe database from file")
        for loaded_recipe in loaded_recipes:
            ingredients = []
            directions = loaded_recipes[loaded_recipe].get("directions", "")
            description = loaded_recipes[loaded_recipe].get("description", "")
            loaded_ingredients = loaded_recipes[loaded_recipe].get("ingredients", [])
            for ingredient in loaded_ingredients:
                if type(ingredient) is str:
                    ingredients.append(Ingredient(name=ingredient))
                else:
                    name = list(ingredient.keys())[0]
                    amount_with_unit = str(ingredient[name].get("amount", "1"))
                    amount, amount_unit = parse_amount(amount_with_unit)
                    print("parsed", amount_with_unit, "into", amount, amount_unit)
                    optional = ingredient[name].get("optional", False)
                    brand = ingredient[name].get("brand", "")
                    vendor = ingredient[name].get("vendor", "")
                    ingredients.append(Ingredient(name=name,
                                                  amount=amount,
                                                  amount_unit=amount_unit,
                                                  optional=optional,
                                                  brand=brand,
                                                  vendor=vendor))
            self.recipes[loaded_recipe] = (Recipe(name=loaded_recipe,
                                                  ingredients=ingredients,
                                                  directions=directions,
                                                  description=description))

