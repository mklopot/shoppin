import yaml

import meal
import recipes
import shopping
import sequence

my_recipes = recipes.Recipes()
my_recipes.load()

with open("dinnerlist.yaml") as f:
    dinnerlist = yaml.load(f)

meals = []
for m in dinnerlist:
    recipelist = []
    for recipe in m:
        recipelist.append(my_recipes.recipes[recipe])
    my_meal = meal.Meal("Dinner", recipelist)
    meals.append(my_meal)
    
my_mealplan =  meal.MealPlan("mealplan", meals)

my_sequence = sequence.Sequence()
my_sequence.load()

my_shopping_list = shopping.ShoppingList(my_sequence)
my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())

for i in my_shopping_list.ingredients:
    print(i)
    print()
