"""
Script to enrich existing database recipes with full metadata:
cuisines, dish types, dietary restrictions, occasions, special equipment,
prep/cook times, photos, storage/reheating notes, pairings, and endorsements.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from apps.recipes.models import Recipe, RecipeRating  # noqa: E402

User = get_user_model()
alice = User.objects.filter(username="alice").first() or User.objects.first()
bob = User.objects.filter(username="bob").first() or User.objects.first()
carol = User.objects.filter(username="carol").first() or User.objects.first()

RECIPE_ENRICHMENTS = {
    "Brisket in the Instant Pot": {
        "cuisine": "American",
        "dish_type": "Stew",
        "meal_type": ["Dinner"],
        "dietary_restrictions": ["Dairy-Free", "Gluten-Free", "Kosher (Meat)"],
        "occasions": ["Christmas", "Party / BBQ", "Winter"],
        "special_equipment": ["Instant Pot"],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 20,
        "cook_time_minutes": 75,
        "storage_instructions": "Store cooled brisket with cooking juices in airtight glass container in the fridge for up to 4 days, or freeze for up to 3 months.",
        "reheating_instructions": "Gently reheat in the microwave or covered in an oven at 325°F with reserved cooking juices until steaming hot.",
        "photo_urls": ["https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=800&q=80"],
        "bibliography": ["Pressure Cooker Perfection by America's Test Kitchen"],
    },
    "Soviet Olivier 'Olivye' Salad": {
        "cuisine": "Russian",
        "dish_type": "Salad",
        "meal_type": ["Lunch", "Dinner", "Appetizer"],
        "dietary_restrictions": ["Dairy-Free"],
        "occasions": ["New Year's", "Christmas", "Party / BBQ", "Winter"],
        "special_equipment": [],
        "difficulty_level": "medium",
        "portions": 8,
        "prep_time_minutes": 40,
        "cook_time_minutes": 25,
        "storage_instructions": "Store dressed salad in refrigerator in an airtight container for up to 3 days. Do not freeze.",
        "reheating_instructions": "Serve chilled straight from refrigerator.",
        "photo_urls": ["https://images.unsplash.com/photo-1540420773420-3366772f4999?auto=format&fit=crop&w=800&q=80"],
        "bibliography": ["Classic Russian Cuisine by Alla Sacharow"],
    },
    "Soviet 'New Years Clock' Salad": {
        "cuisine": "Russian",
        "dish_type": "Salad",
        "meal_type": ["Dinner", "Appetizer"],
        "dietary_restrictions": ["Gluten-Free"],
        "occasions": ["New Year's", "Winter"],
        "special_equipment": ["Springform Pan"],
        "difficulty_level": "medium",
        "portions": 8,
        "prep_time_minutes": 45,
        "cook_time_minutes": 20,
        "storage_instructions": "Keep covered in the refrigerator until ready to serve.",
        "reheating_instructions": "Serve cold.",
        "photo_urls": ["https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=800&q=80"],
    },
    "Russian Vinigret": {
        "cuisine": "Russian",
        "dish_type": "Salad",
        "meal_type": ["Lunch", "Dinner", "Side"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free", "Gluten-Free", "Kosher (Parve)"],
        "occasions": ["Autumn", "Winter", "Christmas", "New Year's"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 30,
        "cook_time_minutes": 40,
        "storage_instructions": "Refrigerate up to 5 days. Flavors improve overnight.",
        "reheating_instructions": "Serve chilled or room temperature.",
        "photo_urls": ["https://images.unsplash.com/photo-1546069901-ba9599a7e63c?auto=format&fit=crop&w=800&q=80"],
    },
    "Morkov-cha Koryo-saram carrot salad": {
        "cuisine": "Korean",
        "dish_type": "Salad",
        "meal_type": ["Side", "Appetizer"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free", "Gluten-Free", "Kosher (Parve)"],
        "occasions": ["Party / BBQ", "Summer"],
        "special_equipment": ["Rolling Pin"],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 25,
        "cook_time_minutes": 5,
        "storage_instructions": "Keep chilled in airtight jar for up to 10 days.",
        "reheating_instructions": "Serve chilled.",
        "photo_urls": ["https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=800&q=80"],
    },
    "Lasagna": {
        "cuisine": "Italian",
        "dish_type": "Casserole",
        "meal_type": ["Dinner"],
        "dietary_restrictions": ["Kosher (Dairy)"],
        "occasions": ["Christmas", "Winter", "Autumn"],
        "special_equipment": ["Casserole Dish", "Oven"],
        "difficulty_level": "medium",
        "portions": 8,
        "prep_time_minutes": 35,
        "cook_time_minutes": 50,
        "storage_instructions": "Cover tightly and refrigerate for up to 4 days, or freeze baked or unbaked up to 2 months.",
        "reheating_instructions": "Bake covered in foil at 350°F for 20 minutes until bubbling.",
        "photo_urls": ["https://images.unsplash.com/photo-1574894709920-11b28e7367e3?auto=format&fit=crop&w=800&q=80"],
        "bibliography": ["Essentials of Classic Italian Cooking by Marcella Hazan"],
    },
    "Eggplant Parmesan": {
        "cuisine": "Italian",
        "dish_type": "Casserole",
        "meal_type": ["Dinner"],
        "dietary_restrictions": ["Vegetarian", "Kosher (Dairy)"],
        "occasions": ["Summer", "Autumn"],
        "special_equipment": ["Casserole Dish", "Oven"],
        "difficulty_level": "medium",
        "portions": 6,
        "prep_time_minutes": 30,
        "cook_time_minutes": 45,
        "storage_instructions": "Refrigerate up to 4 days.",
        "reheating_instructions": "Warm in oven at 350°F for 15 minutes.",
        "photo_urls": ["https://images.unsplash.com/photo-1625944525533-473f1a3d54e7?auto=format&fit=crop&w=800&q=80"],
    },
    "Creamy Corn Casserole": {
        "cuisine": "American",
        "dish_type": "Casserole",
        "meal_type": ["Side", "Dinner"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Thanksgiving", "Christmas", "Autumn"],
        "special_equipment": ["Casserole Dish", "Oven"],
        "difficulty_level": "easy",
        "portions": 8,
        "prep_time_minutes": 10,
        "cook_time_minutes": 45,
        "storage_instructions": "Store covered in refrigerator for up to 4 days.",
        "reheating_instructions": "Microwave 1-2 minutes or oven at 325°F for 10 minutes.",
        "photo_urls": ["https://images.unsplash.com/photo-1551218808-94e220e084d2?auto=format&fit=crop&w=800&q=80"],
    },
    "Sweet Potato Casserole": {
        "cuisine": "American",
        "dish_type": "Casserole",
        "meal_type": ["Side", "Dinner"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Thanksgiving", "Christmas", "Autumn"],
        "special_equipment": ["Casserole Dish", "Oven"],
        "difficulty_level": "easy",
        "portions": 8,
        "prep_time_minutes": 20,
        "cook_time_minutes": 40,
        "storage_instructions": "Refrigerate for up to 5 days.",
        "reheating_instructions": "Reheat in oven at 350°F for 15 minutes.",
        "photo_urls": ["https://images.unsplash.com/photo-1574484284002-952d92456975?auto=format&fit=crop&w=800&q=80"],
    },
    "Veggie Pot Pie": {
        "cuisine": "American",
        "dish_type": "Casserole",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Winter", "Autumn"],
        "special_equipment": ["Casserole Dish", "Oven", "Rolling Pin"],
        "difficulty_level": "medium",
        "portions": 6,
        "prep_time_minutes": 30,
        "cook_time_minutes": 40,
        "storage_instructions": "Store in the fridge for up to 3 days.",
        "reheating_instructions": "Reheat in a 350°F oven to keep pastry crisp.",
        "photo_urls": ["https://images.unsplash.com/photo-1621996346565-e3d5d628169e?auto=format&fit=crop&w=800&q=80"],
    },
    "tacos and burritos": {
        "cuisine": "Mexican",
        "dish_type": "Sandwich",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": [],
        "occasions": ["Party / BBQ", "Weeknight Fast"],
        "special_equipment": ["Cast Iron Skillet"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 15,
        "cook_time_minutes": 15,
        "storage_instructions": "Store meat filling and tortillas separately in airtight containers.",
        "reheating_instructions": "Warm meat in a skillet with 1 tbsp water; warm tortillas in dry pan.",
        "photo_urls": ["https://images.unsplash.com/photo-1565299585323-38d6b0865b47?auto=format&fit=crop&w=800&q=80"],
    },
    "quesadilla": {
        "cuisine": "Mexican",
        "dish_type": "Appetizer",
        "meal_type": ["Lunch", "Snack", "Dinner"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Weeknight Fast"],
        "special_equipment": ["Cast Iron Skillet"],
        "difficulty_level": "easy",
        "portions": 2,
        "prep_time_minutes": 5,
        "cook_time_minutes": 8,
        "storage_instructions": "Best fresh; wrap leftover slices in foil.",
        "reheating_instructions": "Crisp in dry skillet on medium heat for 2 minutes each side.",
        "photo_urls": ["https://images.unsplash.com/photo-1618040996337-56904b7850b9?auto=format&fit=crop&w=800&q=80"],
    },
    "Salsa Verde": {
        "cuisine": "Mexican",
        "dish_type": "Sauce",
        "meal_type": ["Side", "Snack"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Gluten-Free", "Dairy-Free", "Kosher (Parve)"],
        "occasions": ["Summer", "Party / BBQ"],
        "special_equipment": ["Blender"],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 10,
        "cook_time_minutes": 10,
        "storage_instructions": "Keep in an airtight jar in the fridge for up to 7 days.",
        "photo_urls": ["https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=800&q=80"],
    },
    "Spanish rice": {
        "cuisine": "Mexican",
        "dish_type": "Side Dish",
        "meal_type": ["Side", "Dinner"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free", "Gluten-Free"],
        "occasions": ["Party / BBQ"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 10,
        "cook_time_minutes": 25,
        "photo_urls": ["https://images.unsplash.com/photo-1536304993881-ff6e9eefa2a6?auto=format&fit=crop&w=800&q=80"],
    },
    "refried beans": {
        "cuisine": "Mexican",
        "dish_type": "Side Dish",
        "meal_type": ["Side", "Lunch", "Dinner"],
        "dietary_restrictions": ["Vegetarian", "Gluten-Free"],
        "occasions": ["Weeknight Fast"],
        "special_equipment": ["Cast Iron Skillet"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 5,
        "cook_time_minutes": 15,
    },
    "schnitzel": {
        "cuisine": "German",
        "dish_type": "Main",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Dairy-Free"],
        "occasions": ["Autumn", "Winter"],
        "special_equipment": ["Cast Iron Skillet", "Rolling Pin"],
        "difficulty_level": "medium",
        "portions": 4,
        "prep_time_minutes": 20,
        "cook_time_minutes": 12,
        "storage_instructions": "Store wrapped in paper towel in airtight box up to 3 days.",
        "reheating_instructions": "Warm in a 400°F oven on wire rack for 8 minutes to keep crust crispy.",
        "photo_urls": ["https://images.unsplash.com/photo-1599921841143-8190253a93bb?auto=format&fit=crop&w=800&q=80"],
    },
    "stir fry beef": {
        "cuisine": "Chinese",
        "dish_type": "Stew",
        "meal_type": ["Dinner"],
        "dietary_restrictions": ["Dairy-Free"],
        "occasions": ["Weeknight Fast"],
        "special_equipment": ["Wok"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 15,
        "cook_time_minutes": 10,
        "photo_urls": ["https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=800&q=80"],
    },
    "stir fry": {
        "cuisine": "Chinese",
        "dish_type": "Stew",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free"],
        "occasions": ["Weeknight Fast"],
        "special_equipment": ["Wok"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 15,
        "cook_time_minutes": 10,
    },
    "Asian salad": {
        "cuisine": "Chinese",
        "dish_type": "Salad",
        "meal_type": ["Lunch", "Side"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free"],
        "occasions": ["Summer"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 15,
        "cook_time_minutes": 0,
    },
    "smashburgers": {
        "cuisine": "American",
        "dish_type": "Burger",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": [],
        "occasions": ["Party / BBQ", "Summer", "Weeknight Fast"],
        "special_equipment": ["Cast Iron Skillet", "Grill"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 10,
        "cook_time_minutes": 8,
        "photo_urls": ["https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=800&q=80"],
    },
    "black bean burger": {
        "cuisine": "American",
        "dish_type": "Burger",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Summer", "Party / BBQ"],
        "special_equipment": ["Food Processor", "Cast Iron Skillet"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 20,
        "cook_time_minutes": 12,
        "photo_urls": ["https://images.unsplash.com/photo-1520072959219-c595dc870360?auto=format&fit=crop&w=800&q=80"],
    },
    "PB&J Sandwich": {
        "cuisine": "American",
        "dish_type": "Sandwich",
        "meal_type": ["Lunch", "Snack"],
        "dietary_restrictions": ["Vegetarian", "Dairy-Free", "Kosher (Parve)"],
        "occasions": ["Weeknight Fast"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 1,
        "prep_time_minutes": 3,
        "cook_time_minutes": 0,
        "photo_urls": ["https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=800&q=80"],
    },
    "Monte Christo Sandwich": {
        "cuisine": "American",
        "dish_type": "Sandwich",
        "meal_type": ["Breakfast", "Lunch"],
        "dietary_restrictions": [],
        "occasions": ["Weekend", "Party / BBQ"],
        "special_equipment": ["Cast Iron Skillet"],
        "difficulty_level": "medium",
        "portions": 2,
        "prep_time_minutes": 10,
        "cook_time_minutes": 10,
        "photo_urls": ["https://images.unsplash.com/photo-1550547660-d9450f859349?auto=format&fit=crop&w=800&q=80"],
    },
    "minestrone soup": {
        "cuisine": "Italian",
        "dish_type": "Soup",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Vegan", "Vegetarian", "Dairy-Free"],
        "occasions": ["Autumn", "Winter"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 20,
        "cook_time_minutes": 40,
        "photo_urls": ["https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=800&q=80"],
    },
    "butternut squash soup": {
        "cuisine": "American",
        "dish_type": "Soup",
        "meal_type": ["Dinner", "Lunch"],
        "dietary_restrictions": ["Vegetarian", "Gluten-Free"],
        "occasions": ["Autumn", "Winter", "Thanksgiving"],
        "special_equipment": ["Blender"],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 15,
        "cook_time_minutes": 35,
        "photo_urls": ["https://images.unsplash.com/photo-1476718406336-bb5a9690ee2a?auto=format&fit=crop&w=800&q=80"],
    },
    "cold borscht": {
        "cuisine": "Eastern European",
        "dish_type": "Soup",
        "meal_type": ["Lunch", "Dinner"],
        "dietary_restrictions": ["Vegetarian", "Gluten-Free"],
        "occasions": ["Summer"],
        "special_equipment": [],
        "difficulty_level": "easy",
        "portions": 6,
        "prep_time_minutes": 25,
        "cook_time_minutes": 15,
        "photo_urls": ["https://images.unsplash.com/photo-1594041680534-e8c8cdebd659?auto=format&fit=crop&w=800&q=80"],
    },
    "pancakes": {
        "cuisine": "American",
        "dish_type": "Breakfast",
        "meal_type": ["Breakfast"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Birthday", "Summer"],
        "special_equipment": ["Cast Iron Skillet", "Grill"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 10,
        "cook_time_minutes": 15,
        "photo_urls": ["https://images.unsplash.com/photo-1528207776546-365bb710ee93?auto=format&fit=crop&w=800&q=80"],
    },
    "Soft and Chewy Almond Sugar Cookies": {
        "cuisine": "American",
        "dish_type": "Dessert",
        "meal_type": ["Dessert", "Snack"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Christmas", "Birthday", "Party / BBQ"],
        "special_equipment": ["Oven", "Rolling Pin"],
        "difficulty_level": "easy",
        "portions": 24,
        "prep_time_minutes": 25,
        "cook_time_minutes": 12,
        "storage_instructions": "Store in an airtight container with a slice of bread to maintain chewiness for up to a week.",
        "photo_urls": ["https://images.unsplash.com/photo-1499636136210-6f4ee915583e?auto=format&fit=crop&w=800&q=80"],
    },
    "Creamy Mocha Fudge": {
        "cuisine": "American",
        "dish_type": "Dessert",
        "meal_type": ["Dessert"],
        "dietary_restrictions": ["Vegetarian", "Gluten-Free"],
        "occasions": ["Christmas", "Party / BBQ"],
        "special_equipment": ["Casserole Dish"],
        "difficulty_level": "easy",
        "portions": 16,
        "prep_time_minutes": 15,
        "cook_time_minutes": 10,
        "storage_instructions": "Keep chilled in airtight container between layers of wax paper for up to 3 weeks.",
        "photo_urls": ["https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=800&q=80"],
    },
    "S'mores": {
        "cuisine": "American",
        "dish_type": "Dessert",
        "meal_type": ["Dessert", "Snack"],
        "dietary_restrictions": ["Vegetarian"],
        "occasions": ["Summer", "Party / BBQ"],
        "special_equipment": ["Grill"],
        "difficulty_level": "easy",
        "portions": 4,
        "prep_time_minutes": 5,
        "cook_time_minutes": 5,
    },
}

# Fix bad encoding in crêpes name if present
crepe = Recipe.objects.filter(id=58).first()
if crepe and "cr" in crepe.name.lower():
    crepe.name = "Crêpes"
    crepe.cuisine = "French"
    crepe.dish_type = "Dessert"
    crepe.meal_type = ["Breakfast", "Dessert"]
    crepe.dietary_restrictions = ["Vegetarian"]
    crepe.portions = 4
    crepe.prep_time_minutes = 15
    crepe.cook_time_minutes = 20
    crepe.save()

# Update mapped recipes
for title, meta in RECIPE_ENRICHMENTS.items():
    recipe = Recipe.objects.filter(name=title).first()
    if not recipe:
        continue

    for k, v in meta.items():
        setattr(recipe, k, v)
    recipe.save()
    print(f"Updated '{recipe.name}' (Cuisine: {recipe.cuisine}, Type: {recipe.dish_type})")

# Establish some realistic recipe pairings (serve_with)
brisket = Recipe.objects.filter(name="Brisket in the Instant Pot").first()
mashed = Recipe.objects.filter(name__icontains="mashed potatoes").first()
corn = Recipe.objects.filter(name="Corn on the cob").first()
if brisket and mashed and corn:
    brisket.serve_with.add(mashed, corn)

tacos = Recipe.objects.filter(name="tacos and burritos").first()
salsa = Recipe.objects.filter(name="Salsa Verde").first()
rice = Recipe.objects.filter(name="Spanish rice").first()
if tacos and salsa and rice:
    tacos.serve_with.add(salsa, rice)

lasagna = Recipe.objects.filter(name="Lasagna").first()
bread = Recipe.objects.filter(name="garlic bread").first()
if lasagna and bread:
    lasagna.serve_with.add(bread)

# Add endorsements and ratings from sample users
ratings_plan = [
    ("Brisket in the Instant Pot", [(alice, 5, True), (bob, 5, True), (carol, 5, True)]),
    ("Soviet Olivier 'Olivye' Salad", [(alice, 5, True), (bob, 4, True)]),
    ("Lasagna", [(alice, 5, True), (carol, 5, True), (bob, 5, True)]),
    ("tacos and burritos", [(alice, 5, True), (bob, 5, True)]),
    ("Soft and Chewy Almond Sugar Cookies", [(carol, 5, True), (alice, 5, True)]),
    ("Morkov-cha Koryo-saram carrot salad", [(bob, 4, True)]),
    ("smashburgers", [(alice, 5, True), (bob, 5, True)]),
    ("Eggplant Parmesan", [(carol, 4, False), (alice, 5, True)]),
]

for r_name, user_ratings in ratings_plan:
    rec = Recipe.objects.filter(name=r_name).first()
    if rec:
        for u, stars, thumbs in user_ratings:
            if u:
                RecipeRating.objects.update_or_create(
                    recipe=rec,
                    user=u,
                    defaults={"stars": stars, "thumbs_up": thumbs},
                )

print("Enrichment complete!")
