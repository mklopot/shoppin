import yaml
import pickle
import os

import mealplan
import recipes
import shopping
import shopping_list_file
import sequence
import util

picklefile = "appstate.pickle"

def save_state(shoppinglist, mealplan, path=picklefile):
    with open(path, "wb") as f:
        pickle.dump((shoppinglist, mealplan), f)

my_recipes = recipes.Recipes()
my_recipes.load()

my_file = shopping_list_file.ShoppingListFile()
my_file.load()

if os.path.exists(picklefile):
    with open(picklefile, "rb") as f:
        my_shopping_list, my_mealplan = pickle.load(f)
        my_mealplan.recipe_database = my_recipes
else:
    my_mealplan = mealplan.MealPlan("Weekly Meal Plan")
    # my_mealplan.load(recipe_database=my_recipes)

    my_sequence = sequence.Sequence()
    my_sequence.load()

    my_shopping_list = shopping.ShoppingList(my_sequence)
    my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
    my_shopping_list.load_ingredients(my_file.make_shopping_plan())

##############
from bottle import Bottle, template, request, redirect

app = Bottle()

@app.route('/')
def shoppinnglist():
    need = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.NEED]
    got = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.GOT]
    have = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.HAVE]
    recipes_ready_to_cook = []
    for meal in my_mealplan.meals:
        for recipe in meal.recipes:
            if shopping.ItemStatus.NEED not in my_shopping_list.status_by_attribution(recipe):
                recipes_ready_to_cook.append(recipe)
    meals_ready_to_cook = []
    for meal in my_mealplan.meals:
        if len(meal.recipes) == len([recipe for recipe in meal.recipes if recipe in recipes_ready_to_cook]):
            meals_ready_to_cook.append(meal)
    return template("shoppinglist",
                    need=need,
                    got=got,
                    have=have,
                    mealplan=my_mealplan,
                    recipelist=list(my_recipes.recipes.keys()),
                    recipes_ready_to_cook=recipes_ready_to_cook,
                    meals_ready_to_cook=meals_ready_to_cook)

@app.route('/got/<item_id:int>')
def got(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_got()
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/have/<item_id:int>')
def have(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_have()
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/need/<item_id:int>')
def need(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_need()
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/lock/<item_id:int>')
def need(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.lock()
    save_state(my_shopping_list, my_mealplan)
    redirect('/')


@app.route('/add-meal', method=['POST'])
def add_meal():
    if request.POST.meal == "":
        redirect('/')
    my_mealplan.meals.append(mealplan.Meal(name=request.POST.meal))
    my_shopping_list.clear()
    my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
    my_shopping_list.load_ingredients(my_file.make_shopping_plan())

    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/add-recipe', method=['POST'])
def add_recipe():
    try:
        new_recipe = my_recipes.recipes[request.POST.recipe]
        my_mealplan.meals[int(request.POST.meal_index)].recipes.append(new_recipe)
        my_shopping_list.clear()
        my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
        my_shopping_list.load_ingredients(my_file.make_shopping_plan())

    except:
        pass
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/delete-meal/<meal_index:int>')
def delete_meal(meal_index):
    meal = my_mealplan.meals[meal_index]
    for recipe in meal.recipes:
        my_shopping_list.delete_by_attribution(recipe)
    del my_mealplan.meals[meal_index]
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/delete-recipe-from-meal/<meal_index:int>/<recipe_index:int>')
def delete_recipe(meal_index, recipe_index):
    try:
        recipe_to_delete = my_mealplan.meals[meal_index].recipes[recipe_index]
        del my_mealplan.meals[meal_index].recipes[recipe_index]
        my_shopping_list.delete_by_attribution(recipe_to_delete)
    except Exception as e:
        print(e)
    save_state(my_shopping_list, my_mealplan)
    redirect('/')

@app.route('/add-item', method=['POST'])
def add_item():
    if request.POST.name == "":
        redirect("/")
    amount, amount_unit = util.parse_amount(request.POST.amount)
    item = shopping.ShoppingListItem(name=request.POST.name,
                                     amount=amount,
                                     amount_unit=amount_unit,
                                     brand=request.POST.brand,
                                     vendor=request.POST.vendor)
    my_shopping_list.ingredients.append(item)
    item.list = my_shopping_list
    my_shopping_list.deduplicate()
    my_shopping_list._map()
    my_shopping_list.order()
    save_state(my_shopping_list, my_mealplan)
    redirect('/')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=True, reloader=True)
