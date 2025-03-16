import yaml

import meal
import recipes
import shopping
import shopping_list_file
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
    return template("shoppinglist", need=need, got=got, have=have)

@app.route('/got/<item_id:int>')
def got(item_id):
    print("Got ID:", item_id)
    item = my_shopping_list.find_by_id(item_id)
    print("Found:", item)
    if not item:
        raise(ValueError)
    item.set_got()

    redirect('/')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True, reloader=True)
