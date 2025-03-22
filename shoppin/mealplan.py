from dataclasses import dataclass, field
from recipes import Recipe


import yaml


@dataclass
class Meal:
    name: str
    recipes: list[Recipe] = field(default_factory=list)


@dataclass
class MealPlan:
    name: str
    meals: list[Meal] = field(default_factory=list)

    def make_shopping_plan(self):
        ingredient_list = []
        for meal in self.meals:
            for recipe in meal.recipes:
                for ingredient in recipe.ingredients:
                    ingredient_list.append(ingredient)
        return ingredient_list

    def load(self, recipe_database, filepath="dinner-list.yaml"):
        with open(filepath) as f:
            loaded = yaml.load(f)
        for loadedmeal in loaded:
            mealname = list(loadedmeal.keys())[0]
            recipelist = []       
            for recipe in loadedmeal[mealname]:
                try:
                    recipelist.append(recipe_database.recipes[recipe])
                except KeyError:
                    print(recipe, "not found in recipe database", filepath)
                    continue
            self.meals.append(Meal(mealname, recipelist))
