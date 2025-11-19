import pickle
import os
from datetime import datetime
import pytz

import mealplan
import recipes
import shopping
import list_manager


class Appstate:
    """
    Manage application state

    If state is not found in the state file,
    generate new data structures for the recipes database,
    shopping list, list manager, and meal plan.
    """
    def __init__(self,
                 picklepath="appstate.pickle",
                 timezone="UTC"):
        self.picklepath = picklepath
        self.timezone = timezone
        self.recipes = recipes.Recipes()
        self.recipes.load()

        if os.path.exists(self.picklepath):
            with open(self.picklepath, "rb") as f:
                self.shoppinglist, self.mealplan, self.listmanager = pickle.load(f)
                self.mealplan.recipe_database = self.recipes
        else:
            self.shoppinglist = shopping.ShoppingList()
            mealplan_name = datetime.now(
                    pytz.timezone(self.timezone)).strftime("Created %A, %B %d")
            self.mealplan = mealplan.MealPlan(mealplan_name)
            self.mealplan.recipe_database = self.recipes
            self.listmanager = list_manager.ListManager("lists/")

    def save_state(self):
        with open(self.picklepath, "wb") as f:
            pickle.dump(
                    (self.shoppinglist, self.mealplan, self.listmanager), f)

    def clear_state(self):
        self.recipes = recipes.Recipes()
        self.recipes.load()
        self.shoppinglist = shopping.ShoppingList()
        mealplan_name = datetime.now(
                pytz.timezone(self.timezone)).strftime("Created %A, %B %d")
        self.mealplan = mealplan.MealPlan(mealplan_name)
        self.mealplan.recipe_database = self.recipes
        self.listmanager = list_manager.ListManager("lists/")
