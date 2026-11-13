import pickle
import os
from datetime import datetime
import pytz
import logging

import mealplan
import recipes
import shopping
import list_manager
import categories

logger = logging.getLogger("shoppin.appstate")
logger.addHandler(logging.NullHandler())

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

        logger.debug("Loading recipe database")
        self.recipes = recipes.Recipes()
        self.recipes.load()

        if os.path.exists(self.picklepath):
            with open(self.picklepath, "rb") as f:
                logger.debug("Loading application state from picklefile")
                self.shoppinglist, self.mealplan, self.listmanager = pickle.load(f)
                self.mealplan.recipe_database = self.recipes
        else:
            logger.debug("No saved application state found, initializing new application state")
            self.shoppinglist = shopping.ShoppingList(timezone=self.timezone)
            mealplan_name = datetime.now(
                    pytz.timezone(self.timezone)).strftime("Created %A, %B %d")
            self.mealplan = mealplan.MealPlan(mealplan_name)
            self.mealplan.recipe_database = self.recipes
            self.listmanager = list_manager.ListManager("lists/")

    def save_state(self):
        logger.debug("Saving application state to file")
        with open(self.picklepath, "wb") as f:
            pickle.dump(
                    (self.shoppinglist, self.mealplan, self.listmanager), f)

    def clear_state(self):
        logger.debug("Re-initializing application state")
        self.recipes = recipes.Recipes()
        self.recipes.load()
        self.shoppinglist = shopping.ShoppingList(timezone=self.timezone)
        mealplan_name = datetime.now(
                pytz.timezone(self.timezone)).strftime("Created %A, %B %d")
        self.mealplan = mealplan.MealPlan(mealplan_name)
        self.mealplan.recipe_database = self.recipes
        self.listmanager = list_manager.ListManager("lists/")
