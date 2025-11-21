from datetime import datetime
import pytz
from bottle import Bottle, template, request, redirect, static_file
import logging

import shopping
import util
import recipes
import mealplan


logger = logging.getLogger("shoppin.web")
logger.addHandler(logging.NullHandler())

class Web(Bottle):
    def __init__(self, appstate):
        logger.debug(f"Initialized new {self}")
        super(Web, self).__init__()
        self.appstate = appstate

        logger.debug("Registering routes...")
        ######################################################
        # Route decoratorsyntax cannot be used here out of the box.
        # Instead, we have to use the following syntax.
        # You must add a line here for every new route
        self.route('/', callback=self.toplevel)
        self.route('/got/<item_id:int>', callback=self.got)
        self.route('/have/<item_id:int>', callback=self.have)
        self.route('/need/<item_id:int>', callback=self.need)
        self.route('/lock/<item_id:int>', callback=self.lock)
        self.route('/add-meal', method=['POST'], callback=self.add_meal)
        self.route('/add-recipe', method=['POST'], callback=self.add_recipe)
        self.route('/delete-meal/<meal_index:int>', callback=self.delete_meal)
        self.route('/delete-recipe-from-meal/<meal_index:int>/<recipe_index:int>', callback=self.delete_recipe)
        self.route('/add-item', method=['POST'], callback=self.add_item)
        self.route('/include-lists', method=['POST'], callback=self.include_lists)
        self.route('/clear', callback=self.clear)
        self.route('/recipe/<recipe>', callback=self.recipe)
        self.route('/edit-recipe/<recipe>', callback=self.edit_recipe)
        self.route('/save-recipe', method=['POST'], callback=self.save_recipe)
        self.route('/add-ingredient', method=['POST'], callback=self.add_ingredient)
        self.route('/delete-ingredient/<recipe>/<ingredient_index:int>', callback=self.delete_ingredient)
        self.route('/add-recipe-to-database-form', callback=self.add_recipe_to_database_form)
        self.route('/add-recipe-to-database', method='POST', callback=self.add_recipe_to_database)
        self.route('/images/<filename>', callback=self.static)

    def toplevel(self):
        need = [ingredient for ingredient in self.appstate.shoppinglist.items if ingredient.status is shopping.ItemStatus.NEED]
        got = [ingredient for ingredient in self.appstate.shoppinglist.items if ingredient.status is shopping.ItemStatus.GOT]
        have = [ingredient for ingredient in self.appstate.shoppinglist.items if ingredient.status is shopping.ItemStatus.HAVE]

        recipes_ready_to_cook = []
        recipes_only_missing_optional = []
        for meal in self.appstate.mealplan.meals:
            for recipe in meal.recipes:
                status, status_ignore_optional = self.appstate.shoppinglist.status_by_attribution(recipe)
                if shopping.ItemStatus.NEED not in status:
                    recipes_ready_to_cook.append(recipe)
                elif shopping.ItemStatus.NEED not in status_ignore_optional:
                    recipes_only_missing_optional.append(recipe)

        meals_ready_to_cook = []
        meals_only_missing_optional = []
        for meal in self.appstate.mealplan.meals:
            num_ready = len([recipe for recipe in meal.recipes if recipe in recipes_ready_to_cook])
            if len(meal.recipes) == num_ready:
                meals_ready_to_cook.append(meal)
            if len(meal.recipes) == len([recipe for recipe in meal.recipes if recipe in recipes_only_missing_optional]) + num_ready:
                meals_only_missing_optional.append(meal)

        return template("shoppinglist",
                        need=need,
                        got=got,
                        have=have,
                        mealplan=self.appstate.mealplan,
                        list_manager=self.appstate.listmanager,
                        recipelist=list(self.appstate.recipes.recipes.keys()),
                        recipes_ready_to_cook=recipes_ready_to_cook,
                        recipes_only_missing_optional=recipes_only_missing_optional,
                        meals_ready_to_cook=meals_ready_to_cook,
                        meals_only_missing_optional=meals_only_missing_optional)

    def got(self, item_id):
        item = self.appstate.shoppinglist.find_by_id(item_id)

        if item:
            item.set_got()
            item.unlock()
        self.appstate.save_state()
        redirect('/')

    def have(self, item_id):
        item = self.appstate.shoppinglist.find_by_id(item_id)
        if item:
            item.set_have()
            item.unlock()
        self.appstate.save_state()
        redirect('/')

    def need(self, item_id):
        item = self.appstate.shoppinglist.find_by_id(item_id)
        if item:
            item.set_need()
        self.appstate.save_state()
        redirect('/')

    def lock(self, item_id):
        item = self.appstate.shoppinglist.find_by_id(item_id)
        if item:
            item.lock()
        self.appstate.save_state()
        redirect('/')

    def add_meal(self):
        logger.debug(f"Adding new meal to mealplan: {request.POST.meal}")
        if not self.appstate.mealplan.meals:
            self.appstate.mealplan.name = datetime.now(
                    pytz.timezone(self.appstate.timezone)).strftime("Created %A, %B %d")
        if request.POST.meal == "":
            redirect('/')
        self.appstate.mealplan.meals.append(mealplan.Meal(name=request.POST.meal))
        self.appstate.save_state()
        redirect('/')

    def add_recipe(self):
        try:
            new_recipe = self.appstate.recipes.recipes[request.POST.recipe]
            self.appstate.mealplan.meals[int(request.POST.meal_index)].recipes.append(new_recipe)
            logger.debug(f"Adding {new_recipe.name} to meal {self.appstate.mealplan.meals[int(request.POST.meal_index)].name}")
            self.appstate.shoppinglist.load_ingredients(new_recipe.make_shopping_plan())
        except:
            pass
        self.appstate.save_state()
        redirect('/')

    def delete_meal(self, meal_index):
        meal = self.appstate.mealplan.meals[meal_index]
        logger.debug(f"Deleting meal {meal.name} from mealplan")
        for recipe in meal.recipes:
            self.appstate.shoppinglist.delete_by_attribution(recipe)
        del self.appstate.mealplan.meals[meal_index]
        self.appstate.save_state()
        redirect('/')

    def delete_recipe(self, meal_index, recipe_index):
        recipe_to_delete = self.appstate.mealplan.meals[meal_index].recipes[recipe_index]
        logger.debug(f"Removing {recipe_to_delete.name} from meal {self.appstate.mealplan.meals[meal_index].name}")
        del self.appstate.mealplan.meals[meal_index].recipes[recipe_index]
        self.appstate.shoppinglist.delete_by_attribution(recipe_to_delete)
        self.appstate.save_state()
        redirect('/')

    def add_item(self):
        item_name = request.POST.name.strip().strip("?").strip()  # Hi Beth!
        if item_name == "":
            redirect("/")
        logger.debug(f"Manually adding item to shopping list: {item_name}")
        amount, amount_unit = util.parse_amount(request.POST.amount)
        item = shopping.ShoppingListItem(name=item_name,
                                         amount=amount,
                                         amount_unit=amount_unit,
                                         brand=request.POST.brand,
                                         vendor=request.POST.vendor,
                                         purpose=["one-time purchase"])
        item.lock()
        self.appstate.shoppinglist.add_item(item)
        self.appstate.save_state()
        redirect('/')

    def include_lists(self):
        include_set = {int(i) for i in request.POST.keys()}
        for index, sublist in enumerate(self.appstate.listmanager.lists):
            if sublist.include:
                if index not in include_set:
                    sublist.include = False
                    logger.debug(f"Including preset list {sublist.name}")
                    self.appstate.shoppinglist.delete_by_attribution(sublist)
            else:
                if index in include_set:
                    sublist.include = True
                    logger.debug(f"Excluding preset list {sublist.name}")
                    self.appstate.shoppinglist.load_ingredients(sublist.make_shopping_plan())
        self.appstate.save_state()
        redirect('/')

    def clear(self):
        self.appstate.clear_state()
        self.appstate.save_state()
        redirect('/')

    def recipe(self, recipe):
        recipe = self.appstate.recipes.recipes[recipe]
        logger.debug(f'Rendering page for {recipe.name}')
        return template("recipe", recipe=recipe)

    def edit_recipe(self, recipe):
        recipe = self.appstate.recipes.recipes[recipe]
        logger.debug(f'Rendering editing form for {recipe.name}')
        return template("edit-recipe", recipe=recipe)

    def save_recipe(self):
        recipe = self.appstate.recipes.recipes[request.POST.recipe]
        logger.debug(f'Saving recipe {recipe.name}')
        recipe.description = request.POST.description
        recipe.directions = request.POST.directions
        self.appstate.recipes.save()

    def add_ingredient(self):
        recipe = self.appstate.recipes.recipes[request.POST.recipe]
        logger.debug(f"Adding {request.POST.name} as an ingredient for recipe {recipe.name}")
        ingredient_amount, ingredient_amount_unit = util.parse_amount(request.POST.amount)
        new_ingredient = recipes.Ingredient(name=request.POST.name,
                                            amount=ingredient_amount,
                                            amount_unit=ingredient_amount_unit,
                                            optional=bool(request.POST.optional),
                                            brand=request.POST.brand,
                                            vendor=request.POST.vendor,
                                            attribution=recipe,
                                            purpose=recipe.name)
        recipe.ingredients.append(new_ingredient)
        self.appstate.recipes.save()
        redirect(f'/edit-recipe/{recipe.name}')

    def delete_ingredient(self, recipe, ingredient_index):
        recipe = self.appstate.recipes.recipes[recipe]
        ingredient_to_delete = recipe.ingredients[ingredient_index]
        logger.debug(f"Deleting {ingredient_to_delete.name} from ingredients of recipe {recipe.name}")
        del recipe.ingredients[ingredient_index]
        self.appstate.recipes.save()
        redirect(f'/edit-recipe/{recipe.name}')

    def add_recipe_to_database_form(self):
        logger.debug("Rendering form to add new recipe to database")
        return template('new-recipe', name_taken=request.query.name_taken, recipe=request.query.recipe)

    def add_recipe_to_database(self):
        if not request.POST.recipe:
            redirect('/add-recipe-to-database-form')
        if request.POST.recipe in self.appstate.recipes.recipes.keys():
            redirect('/add-recipe-to-database-form?name_taken=true&recipe='+request.POST.recipe)
        else:
            self.appstate.recipes.recipes[request.POST.recipe] = recipes.Recipe(name=request.POST.recipe, ingredients=[])
            redirect('/edit-recipe/'+request.POST.recipe)

    def static(self, filename):
        return static_file(filename, "images/")
