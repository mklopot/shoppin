from datetime import datetime
import pytz
from functools import partial
from bottle import Bottle, template, request, redirect, static_file

import shopping
import util
import recipes
import mealplan


class Web(Bottle):
    def __init__(self,
                 shoppinglist,
                 mealplan,
                 listmanager,
                 recipes,
                 timezone,
                 save_state,
                 clear_state):
        super(Web, self).__init__()
        self.shoppinglist = shoppinglist
        self.mealplan = mealplan
        self.listmanager = listmanager
        self.recipes = recipes
        self.timezone = timezone
        self.save_state = partial(save_state,
                                  self.shoppinglist,
                                  self.mealplan,
                                  self.listmanager)
        self.clear_state = partial(clear_state,
                                   self.shoppinglist,
                                   self.mealplan,
                                   self.listmanager)
        # Route decorators cannot be used here out of the box.
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
        need = [ingredient for ingredient in self.shoppinglist.items if ingredient.status is shopping.ItemStatus.NEED]
        got = [ingredient for ingredient in self.shoppinglist.items if ingredient.status is shopping.ItemStatus.GOT]
        have = [ingredient for ingredient in self.shoppinglist.items if ingredient.status is shopping.ItemStatus.HAVE]

        recipes_ready_to_cook = []
        recipes_only_missing_optional = []
        for meal in self.mealplan.meals:
            for recipe in meal.recipes:
                status, status_ignore_optional = self.shoppinglist.status_by_attribution(recipe)
                if shopping.ItemStatus.NEED not in status:
                    recipes_ready_to_cook.append(recipe)
                elif shopping.ItemStatus.NEED not in status_ignore_optional:
                    recipes_only_missing_optional.append(recipe)

        meals_ready_to_cook = []
        meals_only_missing_optional = []
        for meal in self.mealplan.meals:
            num_ready = len([recipe for recipe in meal.recipes if recipe in recipes_ready_to_cook])
            if len(meal.recipes) == num_ready:
                meals_ready_to_cook.append(meal)
            if len(meal.recipes) == len([recipe for recipe in meal.recipes if recipe in recipes_only_missing_optional]) + num_ready:
                meals_only_missing_optional.append(meal)

        return template("shoppinglist",
                        need=need,
                        got=got,
                        have=have,
                        mealplan=self.mealplan,
                        list_manager = self.listmanager,
                        recipelist=list(self.recipes.recipes.keys()),
                        recipes_ready_to_cook=recipes_ready_to_cook,
                        recipes_only_missing_optional=recipes_only_missing_optional,
                        meals_ready_to_cook=meals_ready_to_cook,
                        meals_only_missing_optional=meals_only_missing_optional)

    def got(self, item_id):
        item = self.shoppinglist.find_by_id(item_id)

        if item:
            item.set_got()
            item.unlock()
        self.save_state()
        redirect('/')

    def have(self, item_id):
        item = self.shoppinglist.find_by_id(item_id)
        if item:
            item.set_have()
            item.unlock()
        self.save_state()
        redirect('/')

    def need(self, item_id):
        item = self.shoppinglist.find_by_id(item_id)
        if item:
            item.set_need()
        self.save_state()
        redirect('/')

    def lock(self, item_id):
        item = self.shopping_list.find_by_id(item_id)
        if item:
            item.lock()
        self.save_state()
        redirect('/')

    def add_meal(self):
        if not self.mealplan.meals:
            self.mealplan.name = datetime.now(pytz.timezone(self.timezone)).strftime("Created %A, %B %d")
        if request.POST.meal == "":
            redirect('/')
        self.mealplan.meals.append(mealplan.Meal(name=request.POST.meal))
        self.save_state()
        redirect('/')

    def add_recipe(self):
        try:
            new_recipe = self.recipes.recipes[request.POST.recipe]
            self.mealplan.meals[int(request.POST.meal_index)].recipes.append(new_recipe)
            self.shoppinglist.load_ingredients(new_recipe.make_shopping_plan())
        except:
            pass
        self.save_state()
        redirect('/')

    def delete_meal(self, meal_index):
        meal = self.mealplan.meals[meal_index]
        for recipe in meal.recipes:
            self.shoppinglist.delete_by_attribution(recipe)
        del self.mealplan.meals[meal_index]
        self.save_state()
        redirect('/')

    def delete_recipe(self, meal_index, recipe_index):
        try:
            recipe_to_delete = self.mealplan.meals[meal_index].recipes[recipe_index]
            del self.mealplan.meals[meal_index].recipes[recipe_index]
            self.shopping_list.delete_by_attribution(recipe_to_delete)
        except Exception as e:
            print(e)
        self.save_state()
        redirect('/')

    def add_item(self):
        item_name = request.POST.name.strip().strip("?").strip() # Hi Beth!
        if item_name == "":
            redirect("/")
        amount, amount_unit = util.parse_amount(request.POST.amount)
        item = shopping.ShoppingListItem(name=item_name,
                                         amount=amount,
                                         amount_unit=amount_unit,
                                         brand=request.POST.brand,
                                         vendor=request.POST.vendor,
                                         purpose=["one-time purchase"])
        item.lock()
        self.shoppinglist.add_item(item)
        self.save_state()
        redirect('/')

    def include_lists(self):
        include_set = {int(i) for i in request.POST.keys()}
        print("include_set:", include_set)
        for index, sublist in enumerate(self.listmanager.lists):
            print("before:", index, sublist, sublist.include)
            if sublist.include:
                if index not in include_set:
                    sublist.include = False
                    print("removing", index, sublist)
                    self.shoppinglist.delete_by_attribution(sublist)
            else:
                if index in include_set:
                    sublist.include = True
                    print("loading", index, sublist)
                    self.shoppinglist.load_ingredients(sublist.make_shopping_plan())
            print("after:", index, sublist, sublist.include)
        self.save_state()
        redirect('/')

    def clear(self):
        self.clear_state()
        self.save_state()
        redirect('/')

    def recipe(self, recipe):
        recipe = self.recipes.recipes[recipe]
        return template("recipe", recipe=recipe)

    def edit_recipe(self, recipe):
        recipe = self.recipes.recipes[recipe]
        return template("edit-recipe", recipe=recipe)

    def save_recipe(self):
        recipe = self.recipes.recipes[request.POST.recipe]
        recipe.description = request.POST.description
        recipe.directions = request.POST.directions
        self.recipes.save()

    def add_ingredient(self):
        recipe = self.recipes.recipes[request.POST.recipe]
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
        self.recipes.save()
        redirect(f'/edit-recipe/{recipe.name}')

    def delete_ingredient(self, recipe, ingredient_index):
        recipe = self.recipes.recipes[recipe]
        del recipe.ingredients[ingredient_index]
        self.recipes.save()
        redirect(f'/edit-recipe/{recipe.name}')

    def add_recipe_to_database_form(self):
        return template('new-recipe', name_taken=request.query.name_taken, recipe=request.query.recipe)

    def add_recipe_to_database(self):
        if not request.POST.recipe:
            redirect('/add-recipe-to-database-form')
        if request.POST.recipe in self.recipes.recipes.keys():
            redirect('/add-recipe-to-database-form?name_taken=true&recipe='+request.POST.recipe)
        else:
            self.recipes.recipes[request.POST.recipe] = recipes.Recipe(name=request.POST.recipe, ingredients=[])
            redirect('/edit-recipe/'+request.POST.recipe)

    def static(self, filename):
        return static_file(filename, "images/")
