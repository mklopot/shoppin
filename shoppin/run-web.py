import yaml

import mealplan
import recipes
import shopping
import shopping_list_file
import sequence

my_recipes = recipes.Recipes()
my_recipes.load()

my_mealplan =  mealplan.MealPlan("Weekly Meal Plan")
my_mealplan.load(recipe_database=my_recipes)

my_file = shopping_list_file.ShoppingListFile()
my_file.load()

my_sequence = sequence.Sequence()
my_sequence.load()

my_shopping_list = shopping.ShoppingList(my_sequence)
my_shopping_list.load_ingredients(my_mealplan.make_shopping_plan())
my_shopping_list.load_ingredients(my_file.make_shopping_plan())


for i in my_shopping_list.ingredients:
    print(i)
    print()

##############
from bottle import Bottle, template, request, redirect

app = Bottle()

@app.route('/')
def shoppinnglist():
    need = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.NEED]
    got = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.GOT]
    have = [ingredient for ingredient in my_shopping_list.ingredients if ingredient.status is shopping.ItemStatus.HAVE]
    return template("shoppinglist", need=need, got=got, have=have, mealplan=my_mealplan)

@app.route('/got/<item_id:int>')
def got(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_got()
    redirect('/')

@app.route('/have/<item_id:int>')
def have(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_have()
    redirect('/')

@app.route('/need/<item_id:int>')
def need(item_id):
    item = my_shopping_list.find_by_id(item_id)
    if item:
        item.set_need()
    redirect('/')



if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True, reloader=True)
