import pickle
import os
from datetime import datetime
import pytz

import mealplan
import recipes
import shopping
import list_manager
from web import Web

timezone = "America/Denver"
picklefile = "appstate.pickle"


def save_state(shoppinglist, mealplan, list_manager, path=picklefile):
    with open(path, "wb") as f:
        pickle.dump((shoppinglist, mealplan, list_manager), f)

def clear_state(shopping_list, meal_plan, listmanager, recipes):
    recipes = recipes.Recipes()
    recipes.load()
    shopping_list = shopping.ShoppingList()
    mealplan_name = datetime.now(pytz.timezone(timezone)).strftime("Created %A, %B %d")
    meal_plan = mealplan.MealPlan(mealplan_name)
    meal_plan.recipe_database = my_recipes
    listmanager = list_manager.ListManager("lists/")


my_recipes = recipes.Recipes()
my_recipes.load()

if os.path.exists(picklefile):
    with open(picklefile, "rb") as f:
        my_shopping_list, my_mealplan, my_list_manager = pickle.load(f)
        my_mealplan.recipe_database = my_recipes
else:
    my_shopping_list = shopping.ShoppingList()
    mealplan_name = datetime.now(pytz.timezone(timezone)).strftime("Created %A, %B %d")
    my_mealplan = mealplan.MealPlan(mealplan_name)
    my_mealplan.recipe_database = my_recipes
    my_list_manager = list_manager.ListManager("lists/")

if __name__ == '__main__':
    webapp = Web(my_shopping_list,
                 my_mealplan,
                 my_list_manager,
                 my_recipes,
                 timezone,
                 save_state,
                 clear_state)
    webapp.run(host='127.0.0.1', port=8000, debug=True, reloader=True)
