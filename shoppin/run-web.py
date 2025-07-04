import yaml
import pickle
import os
from datetime import datetime
import pytz

import mealplan
import recipes
import shopping
import shopping_list_file
import sequence
import util
import list_manager

timezone = "America/Denver"
picklefile = "appstate.pickle"

def save_state(shoppinglist, mealplan, list_manager, path=picklefile):
    with open(path, "wb") as f:
        pickle.dump((shoppinglist, mealplan, list_manager), f)

my_recipes = recipes.Recipes()
my_recipes.load()
# my_sequence = sequence.Sequence()
# my_sequence.load()

if os.path.exists(picklefile):
    with open(picklefile, "rb") as f:
        my_shopping_list, my_mealplan, my_list_manager = pickle.load(f)
        my_mealplan.recipe_database = my_recipes
#        my_shopping_list.sequence = my_sequence
else:
#    my_shopping_list = shopping.ShoppingList(my_sequence)
    my_shopping_list = shopping.ShoppingList()

    mealplan_name = datetime.now(pytz.timezone(timezone)).strftime("Created %A, %B %d")
    my_mealplan = mealplan.MealPlan(mealplan_name)
    my_mealplan.recipe_database = my_recipes
    my_list_manager = list_manager.ListManager("lists/")
##############
from bottle import Bottle, template, request, redirect, static_file

app = Bottle()

@app.route('/')
def shoppinnglist():
    need = [ingredient for ingredient in my_shopping_list.items if ingredient.status is shopping.ItemStatus.NEED]
    got = [ingredient for ingredient in my_shopping_list.items if ingredient.status is shopping.ItemStatus.GOT]
    have = [ingredient for ingredient in my_shopping_list.items if ingredient.status is shopping.ItemStatus.HAVE]

    recipes_ready_to_cook = []
    recipes_only_missing_optional = []
    for meal in my_mealplan.meals:
        for recipe in meal.recipes:
            status, status_ignore_optional = my_shopping_list.status_by_attribution(recipe)
            if shopping.ItemStatus.NEED not in status:
                recipes_ready_to_cook.append(recipe)
            elif shopping.ItemStatus.NEED not in status_ignore_optional:
                recipes_only_missing_optional.append(recipe)

    meals_ready_to_cook = []
    meals_only_missing_optional = []
    for meal in my_mealplan.meals:
        num_ready = len([recipe for recipe in meal.recipes if recipe in recipes_ready_to_cook])
        if len(meal.recipes) == num_ready:
            meals_ready_to_cook.append(meal)
        if len(meal.recipes) == len([recipe for recipe in meal.recipes if recipe in recipes_only_missing_optional]) + num_ready:
            meals_only_missing_optional.append(meal)

    return template("shoppinglist",
                    need=need,
                    got=got,
                    have=have,
                    mealplan=my_mealplan,
                    list_manager = my_list_manager,
                    recipelist=list(my_recipes.recipes.keys()),
                    recipes_ready_to_cook=recipes_ready_to_cook,
                    recipes_only_missing_optional=recipes_only_missing_optional,
                    meals_ready_to_cook=meals_ready_to_cook,
                    meals_only_missing_optional=meals_only_missing_optional)

@app.route('/got/<item_id:int>')
def got(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_got()
        item.unlock()
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/have/<item_id:int>')
def have(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_have()
        item.unlock()
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/need/<item_id:int>')
def need(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_need()
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/lock/<item_id:int>')
def need(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.lock()
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')


@app.route('/add-meal', method=['POST'])
def add_meal():
    global timezone
    if not my_mealplan.meals:
        my_mealplan.name = datetime.now(pytz.timezone(timezone)).strftime("Created %A, %B %d")
    if request.POST.meal == "":
        redirect('/')
    my_mealplan.meals.append(mealplan.Meal(name=request.POST.meal))
    # my_shopping_list.clear()
    # my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
    # my_shopping_list.load_ingredients(my_file.make_shopping_plan())

    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/add-recipe', method=['POST'])
def add_recipe():
    try:
        new_recipe = my_recipes.recipes[request.POST.recipe]
        my_mealplan.meals[int(request.POST.meal_index)].recipes.append(new_recipe)
        # my_shopping_list.clear()
        # my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
        # my_shopping_list.load_ingredients(my_file.make_shopping_plan())
        my_shopping_list.load_ingredients(new_recipe.make_shopping_plan())

    except:
        pass
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/delete-meal/<meal_index:int>')
def delete_meal(meal_index):
    meal = my_mealplan.meals[meal_index]
    for recipe in meal.recipes:
        my_shopping_list.delete_by_attribution(recipe)
    del my_mealplan.meals[meal_index]
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/delete-recipe-from-meal/<meal_index:int>/<recipe_index:int>')
def delete_recipe(meal_index, recipe_index):
    try:
        recipe_to_delete = my_mealplan.meals[meal_index].recipes[recipe_index]
        del my_mealplan.meals[meal_index].recipes[recipe_index]
        my_shopping_list.delete_by_attribution(recipe_to_delete)
    except Exception as e:
        print(e)
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/add-item', method=['POST'])
def add_item():
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
    my_shopping_list.add_item(item)
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/include-lists', method=['POST'])
def include_lists():
    include_set = {int(i) for i in request.POST.keys()}
    print("include_set:", include_set)
    for index, sublist in enumerate(my_list_manager.lists):
        print("before:", index, sublist, sublist.include)
        if sublist.include:
            if index not in include_set:
                sublist.include = False
                print("removing", index, sublist)
                my_shopping_list.delete_by_attribution(sublist)
        else:
            if index in include_set:
                sublist.include = True
                print("loading", index, sublist)
                my_shopping_list.load_ingredients(sublist.make_shopping_plan())
        print("after:", index, sublist, sublist.include)
    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/clear')
def clear():
    global my_shopping_list
    global my_mealplan
    global my_list_manager
    global my_recipes
    global my_sequence
    global timezone

    #my_sequence.reset_pointer()

    my_recipes = recipes.Recipes()
    my_recipes.load()

#     my_shopping_list = shopping.ShoppingList(my_sequence)
    my_shopping_list = shopping.ShoppingList()

    mealplan_name = datetime.now(pytz.timezone(timezone)).strftime("Created %A, %B %d")
    my_mealplan = mealplan.MealPlan(mealplan_name)
    my_mealplan.recipe_database = my_recipes


    my_list_manager = list_manager.ListManager("lists/")

    save_state(my_shopping_list, my_mealplan, my_list_manager)
    redirect('/')

@app.route('/recipe/<recipe>')
def recipe(recipe):
    recipe = my_recipes.recipes[recipe]
    return template("recipe", recipe=recipe)

@app.route('/edit-recipe/<recipe>')
def edit_recipe(recipe):
    recipe = my_recipes.recipes[recipe]
    return template("edit-recipe", recipe=recipe)

@app.route('/save-recipe', method=['POST'])
def save_recipe():
    recipe = my_recipes.recipes[request.POST.recipe]
    recipe.description = request.POST.description
    recipe.directions = request.POST.directions
    my_recipes.save()
    #redirect(f'/recipe/{request.POST.recipe}')

@app.route('/add-ingredient', method=['POST'])
def add_ingredient():
    recipe = my_recipes.recipes[request.POST.recipe]
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
    my_recipes.save()
    redirect(f'/edit-recipe/{recipe.name}')

@app.route('/delete-ingredient/<recipe>/<ingredient_index:int>')
def delete_ingredient(recipe, ingredient_index):
    recipe = my_recipes.recipes[recipe]
    del recipe.ingredients[ingredient_index]
    my_recipes.save()
    redirect(f'/edit-recipe/{recipe.name}')

@app.route('/add-recipe-to-database-form')
def add_recipe_to_database_form():
    return template('new-recipe', name_taken=request.query.name_taken, recipe=request.query.recipe)

@app.route('/add-recipe-to-database', method='POST')
def add_recipe_to_database():
    if not request.POST.recipe:
        redirect('/add-recipe-to-database-form')
    if request.POST.recipe in my_recipes.recipes.keys():
        redirect('/add-recipe-to-database-form?name_taken=true&recipe='+request.POST.recipe)
    else:
        my_recipes.recipes[request.POST.recipe] = recipes.Recipe(name=request.POST.recipe, ingredients=[])
        redirect('/edit-recipe/'+request.POST.recipe)

@app.route('/images/<filename>')
def static(filename):
    return static_file(filename, "images/")

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True, reloader=True)
