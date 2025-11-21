from dataclasses import dataclass, field
from recipes import Recipe


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

