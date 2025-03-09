from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError


from util import parse_amount


@dataclass
class Recipe:
    name: str
    ingredients: list["Ingredient"]
    directions: str = ""
    description: str = ""

@dataclass
class Ingredient:
    name: str
    recipe: Recipe
    amount: float = 1
    amount_unit: str = ""
    optional: bool = False
    brand: str = ""
    vendor: str = ""
 
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
            self.recipes[loaded_recipe] = (Recipe(name=loaded_recipe,
                                                  ingredients=[],
                                                  directions=directions,
                                                  description=description))
            for ingredient in loaded_ingredients:
                if type(ingredient) is str:
                    ingredients.append(Ingredient(name=ingredient, recipe=self.recipes[loaded_recipe]))
                else:
                    name = list(ingredient.keys())[0].strip()
                    amount_with_unit = str(ingredient[name].get("amount", "1"))
                    amount, amount_unit = parse_amount(amount_with_unit)
                    amount_unit = amount_unit.strip()
                    print("parsed", amount_with_unit, "into", amount, amount_unit)
                    optional = ingredient[name].get("optional", False)
                    brand = ingredient[name].get("brand", "").strip()
                    vendor = ingredient[name].get("vendor", "").strip()
                    ingredients.append(Ingredient(name=name,
                                                  amount=amount,
                                                  amount_unit=amount_unit,
                                                  optional=optional,
                                                  brand=brand,
                                                  vendor=vendor,
                                                  recipe=self.recipes[loaded_recipe]))

            self.recipes[loaded_recipe].ingredients = ingredients
