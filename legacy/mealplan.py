from dataclasses import dataclass, field
from recipes import Recipe

import emojify


@dataclass
class Meal:
    name: str
    recipes: list[Recipe] = field(default_factory=list)
    emoji = ""
    emojified = False


@dataclass
class MealPlan:
    name: str
    meals: list[Meal] = field(default_factory=list)
    emojifier = emojify.Emojify()


    def add_meal(self, meal):
        if not meal.emojified:
            meal.emoji = self.emojifier(meal.name)
            meal.emojified = True
        self.meals.append(meal)

    def make_shopping_plan(self):
        ingredient_list = []
        for meal in self.meals:
            for recipe in meal.recipes:
                for ingredient in recipe.ingredients:
                    ingredient_list.append(ingredient)
        return ingredient_list
