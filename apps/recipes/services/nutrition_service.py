"""
Culinary nutritional analysis engine and macro calculation service.

Calculates approximate nutritional values (calories, protein, carbohydrates,
total fat, dietary fiber, and sodium) per serving and for the entire recipe dish
based on ingredient quantities, units, and standard food reference data.

Also provides query and filtering utilities to suggest recipes based on
nutritional criteria (e.g. high-protein, low-carb, keto, low-calorie).
"""

import logging
import re
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from apps.recipes.models import Ingredient, Recipe

logger = logging.getLogger(__name__)

# Nutritional database per 100 grams of standard culinary reference food items
# Values based on USDA FoodData Central standards:
# calories (kcal), protein (g), carbs (g), fat (g), fiber (g), sodium (mg),
# density_g_per_cup (approx grams per 1 cup volume), piece_g (approx grams per 1 count/piece)
FOOD_DATABASE: dict[str, dict[str, Any]] = {
    # --- Meats, Poultry & Seafood ---
    "chicken breast": {
        "cals": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.6, "fiber": 0.0, "sodium": 74,
        "density_g_per_cup": 140, "piece_g": 175,
        "aliases": ["chicken breast", "chicken breasts", "chicken cutlet", "chicken tenderloins", "chicken tenders", "boneless chicken", "skinless chicken breast"],
    },
    "chicken thighs": {
        "cals": 209, "protein": 24.0, "carbs": 0.0, "fat": 12.0, "fiber": 0.0, "sodium": 84,
        "density_g_per_cup": 150, "piece_g": 120,
        "aliases": ["chicken thigh", "chicken thighs", "chicken drumstick", "chicken leg"],
    },
    "chicken (general)": {
        "cals": 190, "protein": 27.0, "carbs": 0.0, "fat": 8.0, "fiber": 0.0, "sodium": 80,
        "density_g_per_cup": 145, "piece_g": 150,
        "aliases": ["chicken", "rotisserie chicken", "cooked chicken", "shredded chicken", "roast chicken"],
    },
    "ground beef": {
        "cals": 250, "protein": 18.0, "carbs": 0.0, "fat": 20.0, "fiber": 0.0, "sodium": 72,
        "density_g_per_cup": 220, "piece_g": 115,  # 1 patty ~ 115g
        "aliases": ["ground beef", "minced beef", "hamburger meat", "beef patty", "patty", "beef patties"],
    },
    "beef steak / brisket / roast": {
        "cals": 240, "protein": 26.0, "carbs": 0.0, "fat": 15.0, "fiber": 0.0, "sodium": 60,
        "density_g_per_cup": 200, "piece_g": 225,
        "aliases": ["beef", "steak", "brisket", "beef chuck", "pot roast", "beef roast", "flank steak", "sirloin"],
    },
    "ground turkey": {
        "cals": 190, "protein": 27.0, "carbs": 0.0, "fat": 8.0, "fiber": 0.0, "sodium": 85,
        "density_g_per_cup": 220, "piece_g": 115,
        "aliases": ["ground turkey", "turkey", "turkey breast", "ground chicken"],
    },
    "pork / pork chops": {
        "cals": 210, "protein": 25.0, "carbs": 0.0, "fat": 12.0, "fiber": 0.0, "sodium": 62,
        "density_g_per_cup": 180, "piece_g": 170,
        "aliases": ["pork", "pork chop", "pork chops", "pork loin", "pork tenderloin", "pork shoulder"],
    },
    "pork sausage / italian sausage": {
        "cals": 320, "protein": 15.0, "carbs": 1.5, "fat": 28.0, "fiber": 0.0, "sodium": 780,
        "density_g_per_cup": 200, "piece_g": 85,
        "aliases": ["italian sausage", "sausage", "ground sausage", "breakfast sausage", "bratwurst", "chorizo"],
    },
    "bacon": {
        "cals": 540, "protein": 37.0, "carbs": 1.4, "fat": 42.0, "fiber": 0.0, "sodium": 1700,
        "density_g_per_cup": 120, "piece_g": 15,  # 1 cooked slice ~ 12-15g
        "aliases": ["bacon", "bacon strips", "pancetta", "prosciutto"],
    },
    "ham": {
        "cals": 145, "protein": 21.0, "carbs": 1.5, "fat": 6.0, "fiber": 0.0, "sodium": 1200,
        "density_g_per_cup": 150, "piece_g": 28,  # 1 deli slice ~ 28g
        "aliases": ["ham", "deli ham", "smoked ham", "canadian bacon"],
    },
    "salmon": {
        "cals": 208, "protein": 20.0, "carbs": 0.0, "fat": 13.0, "fiber": 0.0, "sodium": 59,
        "density_g_per_cup": 180, "piece_g": 170,
        "aliases": ["salmon", "salmon fillet", "salmon fillets", "smoked salmon"],
    },
    "tuna": {
        "cals": 130, "protein": 28.0, "carbs": 0.0, "fat": 1.0, "fiber": 0.0, "sodium": 350,
        "density_g_per_cup": 160, "piece_g": 140,  # 1 can ~ 140g drained
        "aliases": ["tuna", "canned tuna", "albacore", "tuna steak"],
    },
    "shrimp": {
        "cals": 99, "protein": 24.0, "carbs": 0.2, "fat": 0.3, "fiber": 0.0, "sodium": 111,
        "density_g_per_cup": 150, "piece_g": 15,
        "aliases": ["shrimp", "prawns", "shrimps"],
    },
    "white fish": {
        "cals": 90, "protein": 19.0, "carbs": 0.0, "fat": 1.0, "fiber": 0.0, "sodium": 70,
        "density_g_per_cup": 150, "piece_g": 140,
        "aliases": ["fish", "cod", "tilapia", "halibut", "whitefish", "fish fillet", "bass", "snapper"],
    },
    "tofu": {
        "cals": 83, "protein": 10.0, "carbs": 2.0, "fat": 5.0, "fiber": 1.0, "sodium": 10,
        "density_g_per_cup": 250, "piece_g": 100,
        "aliases": ["tofu", "firm tofu", "extra firm tofu", "silken tofu", "bean curd"],
    },

    # --- Dairy & Eggs ---
    "egg": {
        "cals": 143, "protein": 12.6, "carbs": 0.7, "fat": 9.5, "fiber": 0.0, "sodium": 142,
        "density_g_per_cup": 240, "piece_g": 50,  # 1 large egg = 50g -> 72 kcal
        "aliases": ["egg", "eggs", "large egg", "large eggs", "egg yolk", "egg white"],
    },
    "milk": {
        "cals": 61, "protein": 3.2, "carbs": 4.8, "fat": 3.3, "fiber": 0.0, "sodium": 43,
        "density_g_per_cup": 244, "piece_g": 244,
        "aliases": ["milk", "whole milk", "2% milk", "skim milk", "low fat milk", "buttermilk"],
    },
    "butter": {
        "cals": 717, "protein": 0.9, "carbs": 0.1, "fat": 81.0, "fiber": 0.0, "sodium": 580,
        "density_g_per_cup": 227, "piece_g": 113.4,  # 1 stick = 113.4g
        "aliases": ["butter", "unsalted butter", "salted butter", "ghee", "margarine"],
    },
    "heavy cream": {
        "cals": 340, "protein": 2.8, "carbs": 2.7, "fat": 36.0, "fiber": 0.0, "sodium": 38,
        "density_g_per_cup": 240, "piece_g": 15,
        "aliases": ["heavy cream", "heavy whipping cream", "whipping cream", "double cream"],
    },
    "half and half": {
        "cals": 130, "protein": 3.0, "carbs": 4.3, "fat": 11.5, "fiber": 0.0, "sodium": 45,
        "density_g_per_cup": 240, "piece_g": 15,
        "aliases": ["half and half", "half & half", "light cream"],
    },
    "sour cream": {
        "cals": 198, "protein": 2.4, "carbs": 4.6, "fat": 19.4, "fiber": 0.0, "sodium": 53,
        "density_g_per_cup": 240, "piece_g": 25,
        "aliases": ["sour cream", "crema"],
    },
    "cheddar cheese": {
        "cals": 403, "protein": 25.0, "carbs": 1.3, "fat": 33.0, "fiber": 0.0, "sodium": 621,
        "density_g_per_cup": 113, "piece_g": 28,  # 1 slice = 28g
        "aliases": ["cheddar", "cheddar cheese", "sharp cheddar", "shredded cheese", "cheese", "monterey jack", "colby", "swiss cheese", "provolone"],
    },
    "mozzarella cheese": {
        "cals": 300, "protein": 22.0, "carbs": 2.2, "fat": 22.0, "fiber": 0.0, "sodium": 500,
        "density_g_per_cup": 112, "piece_g": 28,
        "aliases": ["mozzarella", "mozzarella cheese", "fresh mozzarella", "shredded mozzarella"],
    },
    "parmesan cheese": {
        "cals": 431, "protein": 38.0, "carbs": 4.1, "fat": 29.0, "fiber": 0.0, "sodium": 1500,
        "density_g_per_cup": 100, "piece_g": 10,
        "aliases": ["parmesan", "parmesan cheese", "parmigiano", "pecorino", "romano"],
    },
    "ricotta cheese": {
        "cals": 174, "protein": 11.0, "carbs": 3.0, "fat": 13.0, "fiber": 0.0, "sodium": 84,
        "density_g_per_cup": 245, "piece_g": 30,
        "aliases": ["ricotta", "ricotta cheese", "cottage cheese"],
    },
    "cream cheese": {
        "cals": 342, "protein": 6.0, "carbs": 4.1, "fat": 34.0, "fiber": 0.0, "sodium": 321,
        "density_g_per_cup": 230, "piece_g": 28,
        "aliases": ["cream cheese", "neufchatel"],
    },
    "yogurt": {
        "cals": 75, "protein": 8.0, "carbs": 6.0, "fat": 2.5, "fiber": 0.0, "sodium": 60,
        "density_g_per_cup": 245, "piece_g": 150,
        "aliases": ["yogurt", "greek yogurt", "plain yogurt"],
    },

    # --- Oils & Cooking Fats ---
    "olive oil": {
        "cals": 884, "protein": 0.0, "carbs": 0.0, "fat": 100.0, "fiber": 0.0, "sodium": 2,
        "density_g_per_cup": 216, "piece_g": 14,  # 1 tbsp ~ 14g -> 120 kcal
        "aliases": ["olive oil", "extra virgin olive oil", "evoo"],
    },
    "avocado oil": {
        "cals": 884, "protein": 0.0, "carbs": 0.0, "fat": 100.0, "fiber": 0.0, "sodium": 0,
        "density_g_per_cup": 216, "piece_g": 14,
        "aliases": ["avocado oil"],
    },
    "vegetable oil / canola oil": {
        "cals": 884, "protein": 0.0, "carbs": 0.0, "fat": 100.0, "fiber": 0.0, "sodium": 0,
        "density_g_per_cup": 218, "piece_g": 14,
        "aliases": ["vegetable oil", "canola oil", "cooking oil", "corn oil", "sunflower oil", "sesame oil", "peanut oil"],
    },
    "coconut oil": {
        "cals": 862, "protein": 0.0, "carbs": 0.0, "fat": 99.0, "fiber": 0.0, "sodium": 0,
        "density_g_per_cup": 218, "piece_g": 14,
        "aliases": ["coconut oil"],
    },

    # --- Grains, Pasta, Bread & Starches ---
    "flour": {
        "cals": 364, "protein": 10.3, "carbs": 76.3, "fat": 1.0, "fiber": 2.7, "sodium": 2,
        "density_g_per_cup": 125, "piece_g": 30,
        "aliases": ["flour", "all purpose flour", "all-purpose flour", "wheat flour", "bread flour"],
    },
    "bread": {
        "cals": 265, "protein": 9.0, "carbs": 49.0, "fat": 3.2, "fiber": 2.7, "sodium": 490,
        "density_g_per_cup": 75, "piece_g": 30,  # 1 slice = 30g -> 80 kcal
        "aliases": ["bread", "sandwich bread", "white bread", "wheat bread", "toast", "slices bread"],
    },
    "hamburger bun": {
        "cals": 280, "protein": 9.0, "carbs": 50.0, "fat": 4.5, "fiber": 2.5, "sodium": 460,
        "density_g_per_cup": 80, "piece_g": 50,  # 1 bun = 50g -> 140 kcal
        "aliases": ["hamburger bun", "hamburger buns", "bun", "buns", "brioche bun", "roll", "dinner roll"],
    },
    "breadcrumbs": {
        "cals": 395, "protein": 13.0, "carbs": 72.0, "fat": 5.0, "fiber": 4.5, "sodium": 730,
        "density_g_per_cup": 108, "piece_g": 20,
        "aliases": ["breadcrumbs", "bread crumbs", "panko", "panko breadcrumbs"],
    },
    "pasta / noodles": {
        "cals": 371, "protein": 13.0, "carbs": 74.0, "fat": 1.5, "fiber": 3.2, "sodium": 6,
        "density_g_per_cup": 100, "piece_g": 20,  # 1 lasagna noodle ~ 20g dry
        "aliases": ["pasta", "noodles", "spaghetti", "macaroni", "penne", "lasagna noodles", "egg noodles", "fettuccine", "rigatoni"],
    },
    "rice": {
        "cals": 365, "protein": 7.1, "carbs": 80.0, "fat": 0.7, "fiber": 1.3, "sodium": 5,
        "density_g_per_cup": 185, "piece_g": 185,
        "aliases": ["rice", "white rice", "jasmine rice", "basmati rice", "brown rice", "long grain rice"],
    },
    "oats": {
        "cals": 389, "protein": 16.9, "carbs": 66.3, "fat": 6.9, "fiber": 10.6, "sodium": 2,
        "density_g_per_cup": 90, "piece_g": 40,
        "aliases": ["oats", "oatmeal", "rolled oats", "quick oats"],
    },
    "potatoes": {
        "cals": 77, "protein": 2.0, "carbs": 17.5, "fat": 0.1, "fiber": 2.2, "sodium": 6,
        "density_g_per_cup": 150, "piece_g": 150,  # 1 medium potato ~ 150g
        "aliases": ["potato", "potatoes", "russet potato", "red potato", "hashbrowns", "hash browns", "mashed potatoes"],
    },
    "sweet potatoes": {
        "cals": 86, "protein": 1.6, "carbs": 20.1, "fat": 0.1, "fiber": 3.0, "sodium": 55,
        "density_g_per_cup": 150, "piece_g": 150,
        "aliases": ["sweet potato", "sweet potatoes", "yam", "yams"],
    },
    "cornstarch": {
        "cals": 381, "protein": 0.3, "carbs": 91.0, "fat": 0.1, "fiber": 0.9, "sodium": 9,
        "density_g_per_cup": 128, "piece_g": 10,
        "aliases": ["cornstarch", "corn starch"],
    },

    # --- Beans, Legumes & Canned Goods ---
    "beans (canned)": {
        "cals": 110, "protein": 7.0, "carbs": 20.0, "fat": 0.5, "fiber": 6.5, "sodium": 350,
        "density_g_per_cup": 250, "piece_g": 425,  # 1 standard can = 425g (15 oz)
        "aliases": ["beans", "black beans", "cannellini beans", "kidney beans", "pinto beans", "chickpeas", "garbanzo beans", "seasoned beans", "white beans"],
    },
    "lentils": {
        "cals": 116, "protein": 9.0, "carbs": 20.0, "fat": 0.4, "fiber": 7.9, "sodium": 2,
        "density_g_per_cup": 200, "piece_g": 200,
        "aliases": ["lentils", "brown lentils", "red lentils"],
    },

    # --- Vegetables & Produce ---
    "onion": {
        "cals": 40, "protein": 1.1, "carbs": 9.3, "fat": 0.1, "fiber": 1.7, "sodium": 4,
        "density_g_per_cup": 160, "piece_g": 150,  # 1 medium onion = 150g -> 60 kcal
        "aliases": ["onion", "yellow onion", "white onion", "red onion", "onions", "med onion"],
    },
    "green onion / scallion": {
        "cals": 32, "protein": 1.8, "carbs": 7.3, "fat": 0.2, "fiber": 2.6, "sodium": 16,
        "density_g_per_cup": 100, "piece_g": 15,
        "aliases": ["green onion", "green onions", "scallion", "scallions", "chives"],
    },
    "garlic": {
        "cals": 149, "protein": 6.4, "carbs": 33.1, "fat": 0.5, "fiber": 2.1, "sodium": 17,
        "density_g_per_cup": 136, "piece_g": 3.0,  # 1 clove ~ 3g -> ~4.5 kcal
        "aliases": ["garlic", "garlic cloves", "cloves garlic", "garlic clove", "minced garlic"],
    },
    "carrot": {
        "cals": 41, "protein": 0.9, "carbs": 9.6, "fat": 0.2, "fiber": 2.8, "sodium": 69,
        "density_g_per_cup": 128, "piece_g": 60,  # 1 medium carrot ~ 60g -> 25 kcal
        "aliases": ["carrot", "carrots", "baby carrots"],
    },
    "celery": {
        "cals": 14, "protein": 0.7, "carbs": 3.0, "fat": 0.2, "fiber": 1.6, "sodium": 80,
        "density_g_per_cup": 100, "piece_g": 40,  # 1 stalk/rib ~ 40g -> 6 kcal
        "aliases": ["celery", "celery ribs", "celery stalks", "ribs celery"],
    },
    "bell pepper": {
        "cals": 26, "protein": 1.0, "carbs": 6.0, "fat": 0.3, "fiber": 2.1, "sodium": 4,
        "density_g_per_cup": 150, "piece_g": 120,  # 1 pepper ~ 120g -> 31 kcal
        "aliases": ["bell pepper", "red bell pepper", "green bell pepper", "yellow bell pepper", "peppers", "sweet pepper"],
    },
    "tomatoes": {
        "cals": 18, "protein": 0.9, "carbs": 3.9, "fat": 0.2, "fiber": 1.2, "sodium": 5,
        "density_g_per_cup": 180, "piece_g": 125,  # 1 medium tomato ~ 125g -> 22 kcal
        "aliases": ["tomato", "tomatoes", "roma tomato", "cherry tomatoes", "diced tomatoes", "canned tomatoes"],
    },
    "tomato paste": {
        "cals": 82, "protein": 4.3, "carbs": 18.9, "fat": 0.5, "fiber": 4.1, "sodium": 59,
        "density_g_per_cup": 260, "piece_g": 170,  # 1 small 6oz can ~ 170g
        "aliases": ["tomato paste"],
    },
    "marinara / tomato sauce": {
        "cals": 65, "protein": 1.5, "carbs": 10.0, "fat": 2.0, "fiber": 2.0, "sodium": 450,
        "density_g_per_cup": 250, "piece_g": 250,
        "aliases": ["marinara", "marinara sauce", "tomato sauce", "pasta sauce", "pizza sauce"],
    },
    "corn": {
        "cals": 86, "protein": 3.2, "carbs": 19.0, "fat": 1.2, "fiber": 2.0, "sodium": 15,
        "density_g_per_cup": 145, "piece_g": 90,  # 1 ear / cob ~ 90g kernels
        "aliases": ["corn", "frozen corn", "corn on the cob", "sweet corn", "canned corn"],
    },
    "broccoli": {
        "cals": 34, "protein": 2.8, "carbs": 6.6, "fat": 0.4, "fiber": 2.6, "sodium": 33,
        "density_g_per_cup": 91, "piece_g": 150,
        "aliases": ["broccoli", "broccoli florets"],
    },
    "kale": {
        "cals": 49, "protein": 4.3, "carbs": 8.8, "fat": 0.9, "fiber": 3.6, "sodium": 38,
        "density_g_per_cup": 67, "piece_g": 100,
        "aliases": ["kale", "lacinato kale", "curly kale"],
    },
    "spinach": {
        "cals": 23, "protein": 2.9, "carbs": 3.6, "fat": 0.4, "fiber": 2.2, "sodium": 79,
        "density_g_per_cup": 30, "piece_g": 30,
        "aliases": ["spinach", "baby spinach"],
    },
    "cabbage": {
        "cals": 25, "protein": 1.3, "carbs": 5.8, "fat": 0.1, "fiber": 2.5, "sodium": 18,
        "density_g_per_cup": 70, "piece_g": 800,  # 1 head ~ 800g
        "aliases": ["cabbage", "green cabbage", "red cabbage", "slaw"],
    },
    "avocado": {
        "cals": 160, "protein": 2.0, "carbs": 8.5, "fat": 14.7, "fiber": 6.7, "sodium": 7,
        "density_g_per_cup": 150, "piece_g": 150,  # 1 medium avocado ~ 150g
        "aliases": ["avocado", "avocados", "ripe avocado", "ripe avocados"],
    },
    "mushrooms": {
        "cals": 22, "protein": 3.1, "carbs": 3.3, "fat": 0.3, "fiber": 1.0, "sodium": 5,
        "density_g_per_cup": 70, "piece_g": 18,
        "aliases": ["mushrooms", "mushroom", "button mushrooms", "cremini", "portobello"],
    },
    "cucumber": {
        "cals": 15, "protein": 0.7, "carbs": 3.6, "fat": 0.1, "fiber": 0.5, "sodium": 2,
        "density_g_per_cup": 104, "piece_g": 200,
        "aliases": ["cucumber", "cucumbers", "pickles"],
    },
    "zucchini / squash": {
        "cals": 17, "protein": 1.2, "carbs": 3.1, "fat": 0.3, "fiber": 1.0, "sodium": 8,
        "density_g_per_cup": 124, "piece_g": 180,
        "aliases": ["zucchini", "squash", "yellow squash"],
    },
    "eggplant": {
        "cals": 25, "protein": 1.0, "carbs": 6.0, "fat": 0.2, "fiber": 3.0, "sodium": 2,
        "density_g_per_cup": 82, "piece_g": 400,
        "aliases": ["eggplant", "aubergine"],
    },
    "cilantro / herbs": {
        "cals": 23, "protein": 2.1, "carbs": 3.7, "fat": 0.5, "fiber": 2.8, "sodium": 46,
        "density_g_per_cup": 16, "piece_g": 40,  # 1 bunch ~ 40g
        "aliases": ["cilantro", "fresh cilantro", "parsley", "fresh parsley", "dill", "fresh dill", "basil", "fresh basil", "mint", "rosemary", "thyme"],
    },

    # --- Fruits ---
    "banana": {
        "cals": 89, "protein": 1.1, "carbs": 22.8, "fat": 0.3, "fiber": 2.6, "sodium": 1,
        "density_g_per_cup": 150, "piece_g": 118,  # 1 medium banana = 118g -> 105 kcal
        "aliases": ["banana", "bananas"],
    },
    "apple": {
        "cals": 52, "protein": 0.3, "carbs": 13.8, "fat": 0.2, "fiber": 2.4, "sodium": 1,
        "density_g_per_cup": 125, "piece_g": 180,
        "aliases": ["apple", "apples"],
    },
    "lime / lemon": {
        "cals": 29, "protein": 0.7, "carbs": 9.0, "fat": 0.2, "fiber": 2.8, "sodium": 2,
        "density_g_per_cup": 240, "piece_g": 45,  # 1 lime juice/fruit ~ 45g
        "aliases": ["lime", "limes", "lemon", "lemons", "lime juice", "lemon juice"],
    },
    "berries": {
        "cals": 50, "protein": 1.0, "carbs": 12.0, "fat": 0.4, "fiber": 4.0, "sodium": 1,
        "density_g_per_cup": 150, "piece_g": 15,
        "aliases": ["berries", "strawberries", "blueberries", "raspberries", "blackberries"],
    },

    # --- Condiments, Sweeteners, Nuts & Spreads ---
    "peanut butter": {
        "cals": 588, "protein": 25.0, "carbs": 20.0, "fat": 50.0, "fiber": 6.0, "sodium": 420,
        "density_g_per_cup": 258, "piece_g": 16,  # 1 tbsp ~ 16g -> ~94 kcal
        "aliases": ["peanut butter", "almond butter", "nut butter"],
    },
    "peanuts / nuts": {
        "cals": 600, "protein": 20.0, "carbs": 18.0, "fat": 52.0, "fiber": 7.0, "sodium": 5,
        "density_g_per_cup": 140, "piece_g": 30,
        "aliases": ["peanuts", "almonds", "walnuts", "cashews", "pecans", "nuts"],
    },
    "jam / jelly": {
        "cals": 250, "protein": 0.4, "carbs": 65.0, "fat": 0.1, "fiber": 1.0, "sodium": 18,
        "density_g_per_cup": 320, "piece_g": 20,  # 1 tbsp ~ 20g -> 50 kcal
        "aliases": ["jam", "jelly", "preserves", "marmalade"],
    },
    "ketchup": {
        "cals": 101, "protein": 1.0, "carbs": 27.0, "fat": 0.1, "fiber": 0.3, "sodium": 907,
        "density_g_per_cup": 272, "piece_g": 17,  # 1 tbsp ~ 17g
        "aliases": ["ketchup", "catsup"],
    },
    "mayonnaise": {
        "cals": 680, "protein": 1.0, "carbs": 0.6, "fat": 75.0, "fiber": 0.0, "sodium": 635,
        "density_g_per_cup": 220, "piece_g": 14,  # 1 tbsp ~ 14g -> 95 kcal
        "aliases": ["mayonnaise", "mayo"],
    },
    "mustard": {
        "cals": 66, "protein": 4.4, "carbs": 5.8, "fat": 4.0, "fiber": 3.3, "sodium": 1135,
        "density_g_per_cup": 240, "piece_g": 15,
        "aliases": ["mustard", "dijon mustard", "yellow mustard"],
    },
    "soy sauce": {
        "cals": 53, "protein": 8.0, "carbs": 4.9, "fat": 0.1, "fiber": 0.8, "sodium": 5586,
        "density_g_per_cup": 240, "piece_g": 15,  # 1 tbsp ~ 15g
        "aliases": ["soy sauce", "tamari", "teriyaki sauce"],
    },
    "vinegar": {
        "cals": 18, "protein": 0.0, "carbs": 0.9, "fat": 0.0, "fiber": 0.0, "sodium": 2,
        "density_g_per_cup": 240, "piece_g": 15,
        "aliases": ["vinegar", "white vinegar", "apple cider vinegar", "balsamic vinegar", "red wine vinegar", "rice vinegar"],
    },
    "sugar": {
        "cals": 387, "protein": 0.0, "carbs": 100.0, "fat": 0.0, "fiber": 0.0, "sodium": 1,
        "density_g_per_cup": 200, "piece_g": 12,  # 1 tbsp ~ 12g -> 46 kcal
        "aliases": ["sugar", "white sugar", "granulated sugar", "brown sugar"],
    },
    "honey / maple syrup": {
        "cals": 304, "protein": 0.3, "carbs": 82.0, "fat": 0.0, "fiber": 0.2, "sodium": 4,
        "density_g_per_cup": 340, "piece_g": 21,  # 1 tbsp ~ 21g -> 64 kcal
        "aliases": ["honey", "maple syrup", "syrup", "agave"],
    },
    "chocolate / chocolate chips": {
        "cals": 500, "protein": 5.0, "carbs": 63.0, "fat": 28.0, "fiber": 7.0, "sodium": 24,
        "density_g_per_cup": 170, "piece_g": 30,
        "aliases": ["chocolate", "chocolate chips", "dark chocolate", "cocoa powder"],
    },
    "broth / stock": {
        "cals": 15, "protein": 2.0, "carbs": 1.0, "fat": 0.5, "fiber": 0.0, "sodium": 350,
        "density_g_per_cup": 240, "piece_g": 240,
        "aliases": ["broth", "chicken broth", "beef broth", "vegetable broth", "stock", "chicken stock", "beef stock"],
    },
    "sauces / seasonings (condiments)": {
        "cals": 75, "protein": 1.0, "carbs": 12.0, "fat": 2.0, "fiber": 0.5, "sodium": 600,
        "density_g_per_cup": 240, "piece_g": 15,
        "aliases": ["worcestershire sauce", "hot sauce", "bbq sauce", "barbecue sauce", "sriracha"],
    },

    # --- Zero / Negligible Calorie Items ---
    "negligible / water": {
        "cals": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0, "sodium": 0,
        "density_g_per_cup": 240, "piece_g": 1,
        "aliases": [
            "water", "ice", "salt", "kosher salt", "sea salt", "table salt",
            "black pepper", "pepper", "ground black pepper",
            "italian seasoning", "garlic powder", "onion powder", "paprika",
            "cumin", "chili powder", "oregano", "cinnamon", "nutmeg",
            "baking powder", "baking soda", "vanilla extract", "cooking spray",
        ],
    },
}

# Pre-compile alias lookup index for fast substring and token matching
_ALIAS_INDEX: list[tuple[str, str, dict[str, Any]]] = []
for primary_key, data in FOOD_DATABASE.items():
    for alias in data.get("aliases", [primary_key]):
        _ALIAS_INDEX.append((alias.lower(), primary_key, data))
# Sort index with longest alias matches first for greedy token matching
_ALIAS_INDEX.sort(key=lambda item: len(item[0]), reverse=True)

# Words to strip out when matching ingredient names
PREPARATION_WORDS: set[str] = {
    "fresh", "diced", "chopped", "sliced", "minced", "ripe", "peeled",
    "crushed", "cooked", "raw", "boneless", "skinless", "ground", "canned",
    "frozen", "organic", "low fat", "fat free", "unsalted", "salted",
    "kosher", "fine", "pure", "dry", "dried", "shredded", "grated",
    "large", "medium", "med", "small", "to taste", "optional", "finely", "coarsely",
    "extra", "virgin", "warm", "cold", "melted", "softened", "chilled",
}


def clean_food_name(name: str) -> str:
    """
    Normalize ingredient text by removing parentheticals, punctuation, and preparation adjectives.
    """
    clean = name.lower().strip()
    # Remove nested or single parentheticals e.g. "onion ((1 cup), finely chopped)"
    while "(" in clean and ")" in clean:
        new_clean = re.sub(r"\([^()]*\)", "", clean)
        if new_clean == clean:
            break
        clean = new_clean
    clean = clean.replace("(", " ").replace(")", " ")
    # Remove punctuation
    clean = re.sub(r"[,;:\*\-]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Strip recognized preparation adjectives
    words = clean.split()
    filtered = [w for w in words if w not in PREPARATION_WORDS]
    if filtered:
        return " ".join(filtered)
    return clean


def match_ingredient_to_food(name: str, category: str = "") -> tuple[dict[str, Any], bool, str]:
    """
    Match an ingredient name to a food entry in the nutritional database.

    Returns:
        tuple of (food_data_dict, was_exact_or_alias_matched, food_label).
    """
    cleaned = clean_food_name(name)

    # 1. Direct and Alias matching (longest matches first)
    for alias, primary_name, data in _ALIAS_INDEX:
        # Exact match or word-boundary match
        if alias == cleaned or alias == name.lower().strip():
            return data, True, primary_name
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, cleaned) or re.search(pattern, name.lower()):
            return data, True, primary_name

    # 2. Token overlap fallback
    cleaned_tokens = set(cleaned.split())
    for alias, primary_name, data in _ALIAS_INDEX:
        alias_tokens = set(alias.split())
        if alias_tokens and alias_tokens.issubset(cleaned_tokens):
            return data, True, primary_name

    # 3. Category-based fallback approximation if completely unlisted
    cat_lower = (category or "").lower()
    if cat_lower in ("meat", "poultry", "pork", "beef"):
        fallback = FOOD_DATABASE["chicken (general)"]
        return fallback, False, "meat (approx)"
    if cat_lower in ("dairy", "cheese"):
        fallback = FOOD_DATABASE["cheddar cheese"]
        return fallback, False, "dairy (approx)"
    if cat_lower in ("produce", "vegetables", "fruits"):
        fallback = FOOD_DATABASE["carrot"]
        return fallback, False, "produce (approx)"
    if cat_lower in ("bakery", "grains", "pasta"):
        fallback = FOOD_DATABASE["bread"]
        return fallback, False, "grain (approx)"

    # Default general fallback
    return {
        "cals": 120, "protein": 3.0, "carbs": 15.0, "fat": 4.0, "fiber": 1.0, "sodium": 150,
        "density_g_per_cup": 150, "piece_g": 50,
    }, False, "general staple"


def convert_ingredient_to_grams(amount: float, unit: str, food: dict[str, Any]) -> float:
    """
    Convert an ingredient quantity and unit into approximate weight in grams.
    """
    amt = max(0.0, float(amount))
    u = unit.lower().strip()

    # --- Weight Units ---
    if u in ("g", "gram", "grams"):
        return amt * 1.0
    if u in ("kg", "kilogram", "kilograms"):
        return amt * 1000.0
    if u in ("oz", "ounce", "ounces"):
        return amt * 28.3495
    if u in ("lb", "lbs", "pound", "pounds"):
        return amt * 453.592

    # --- Volume Units (convert to ml, then scale by food density) ---
    volume_ml = None
    if u in ("tsp", "teaspoon", "teaspoons", "t"):
        volume_ml = amt * 5.0
    elif u in ("tbsp", "tablespoon", "tablespoons", "tbs", "tb", "t"):
        volume_ml = amt * 15.0
    elif u in ("fl oz", "fl. oz", "fluid ounce", "fluid ounces"):
        volume_ml = amt * 29.57
    elif u in ("cup", "cups", "c"):
        volume_ml = amt * 240.0
    elif u in ("pt", "pint", "pints"):
        volume_ml = amt * 473.0
    elif u in ("qt", "quart", "quarts"):
        volume_ml = amt * 946.0
    elif u in ("gal", "gallon", "gallons"):
        volume_ml = amt * 3785.0
    elif u in ("ml", "milliliter", "milliliters"):
        volume_ml = amt * 1.0
    elif u in ("l", "liter", "liters"):
        volume_ml = amt * 1000.0
    elif u in ("pinch", "pinches", "dash", "dashes", "splash", "sprig", "sprigs"):
        return amt * 0.5

    if volume_ml is not None:
        density_g_per_cup = float(food.get("density_g_per_cup", 200.0))
        density_g_per_ml = density_g_per_cup / 240.0
        return volume_ml * density_g_per_ml

    # --- Count / Container Units ---
    piece_g = float(food.get("piece_g", 50.0))
    if u in ("slice", "slices"):
        # bread, cheese, bacon slice
        return amt * (30.0 if "bread" in food.get("aliases", []) else (15.0 if "bacon" in food.get("aliases", []) else 28.0))
    if u in ("clove", "cloves"):
        return amt * 3.0
    if u in ("can", "cans"):
        return amt * 425.0  # standard 15-ounce can
    if u in ("small can", "small cans"):
        return amt * 170.0  # 6-ounce can
    if u in ("stick", "sticks"):
        return amt * 113.4  # 1 stick butter = 113.4g
    if u in ("head", "heads"):
        return amt * (800.0 if "cabbage" in food.get("aliases", []) else 40.0)
    if u in ("bunch", "bunches"):
        return amt * 40.0  # fresh herb bunch
    if u in ("ear", "ears"):
        return amt * 90.0  # ear of corn
    if u in ("rib", "ribs", "stalk", "stalks"):
        return amt * 40.0  # celery rib
    if u in ("package", "packages", "pkg", "pkgs", "bag", "box"):
        return amt * 300.0
    if u in ("bun", "buns"):
        return amt * 50.0
    if u in ("patty", "patties"):
        return amt * 115.0
    if u in ("noodles",):
        return amt * 20.0

    # Count without unit or unrecognized unit
    return amt * piece_g


def calculate_ingredient_nutrition(ingredient: Ingredient) -> dict[str, Any]:
    """
    Calculate approximate nutritional values for an individual ingredient.
    """
    food, matched, matched_food = match_ingredient_to_food(ingredient.name, ingredient.category)
    weight_g = convert_ingredient_to_grams(float(ingredient.amount), ingredient.amount_unit, food)

    ratio = weight_g / 100.0
    calories = int(round(food["cals"] * ratio))
    protein_g = round(food["protein"] * ratio, 1)
    carbs_g = round(food["carbs"] * ratio, 1)
    fat_g = round(food["fat"] * ratio, 1)
    fiber_g = round(food["fiber"] * ratio, 1)
    sodium_mg = int(round(food["sodium"] * ratio))

    return {
        "ingredient_id": ingredient.id,
        "name": ingredient.name,
        "raw_display": f"{ingredient.amount:g} {ingredient.amount_unit} {ingredient.name}".strip(),
        "amount": float(ingredient.amount),
        "amount_unit": ingredient.amount_unit,
        "weight_g": round(weight_g, 1),
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "fiber_g": fiber_g,
        "sodium_mg": sodium_mg,
        "matched": matched,
        "matched_food": matched_food,
    }


def calculate_recipe_nutrition(recipe: Recipe) -> dict[str, Any]:
    """
    Calculate aggregate recipe and per-serving nutritional analysis from its ingredients.
    """
    portions = max(1, recipe.portions or 1)
    ingredients = list(recipe.ingredients.all())

    items = []
    tot_cals = 0
    tot_protein = 0.0
    tot_carbs = 0.0
    tot_fat = 0.0
    tot_fiber = 0.0
    tot_sodium = 0
    matched_count = 0

    for ing in ingredients:
        res = calculate_ingredient_nutrition(ing)
        items.append(res)
        tot_cals += res["calories"]
        tot_protein += res["protein_g"]
        tot_carbs += res["carbs_g"]
        tot_fat += res["fat_g"]
        tot_fiber += res["fiber_g"]
        tot_sodium += res["sodium_mg"]
        if res["matched"]:
            matched_count += 1

    per_serving_cals = int(round(tot_cals / portions))
    per_serving_protein = round(tot_protein / portions, 1)
    per_serving_carbs = round(tot_carbs / portions, 1)
    per_serving_fat = round(tot_fat / portions, 1)
    per_serving_fiber = round(tot_fiber / portions, 1)
    per_serving_sodium = int(round(tot_sodium / portions))

    # Calculate caloric ratio split
    p_cals = per_serving_protein * 4.0
    c_cals = per_serving_carbs * 4.0
    f_cals = per_serving_fat * 9.0
    sum_macro_cals = p_cals + c_cals + f_cals

    if sum_macro_cals > 0:
        protein_pct = int(round((p_cals / sum_macro_cals) * 100))
        carbs_pct = int(round((c_cals / sum_macro_cals) * 100))
        fat_pct = max(0, 100 - (protein_pct + carbs_pct))
    else:
        protein_pct = carbs_pct = fat_pct = 0

    coverage_pct = int(round((matched_count / len(ingredients)) * 100)) if ingredients else 100

    return {
        "source": "calculated",
        "portions": portions,
        "per_serving": {
            "calories": per_serving_cals,
            "protein_g": per_serving_protein,
            "carbs_g": per_serving_carbs,
            "fat_g": per_serving_fat,
            "fiber_g": per_serving_fiber,
            "sodium_mg": per_serving_sodium,
        },
        "total_recipe": {
            "calories": tot_cals,
            "protein_g": round(tot_protein, 1),
            "carbs_g": round(tot_carbs, 1),
            "fat_g": round(tot_fat, 1),
            "fiber_g": round(tot_fiber, 1),
            "sodium_mg": tot_sodium,
        },
        "macro_percentages": {
            "protein_pct": protein_pct,
            "carbs_pct": carbs_pct,
            "fat_pct": fat_pct,
        },
        "coverage": {
            "matched_count": matched_count,
            "total_count": len(ingredients),
            "percent": coverage_pct,
        },
        "ingredient_breakdown": items,
    }


def update_recipe_nutrition(recipe: Recipe, save: bool = True) -> dict[str, Any]:
    """
    Compute and update the recipe's nutritional fields and metadata.
    """
    data = calculate_recipe_nutrition(recipe)
    per_serving = data["per_serving"]

    recipe.calories_per_serving = per_serving["calories"]
    recipe.protein_per_serving_g = Decimal(str(per_serving["protein_g"]))
    recipe.carbs_per_serving_g = Decimal(str(per_serving["carbs_g"]))
    recipe.fat_per_serving_g = Decimal(str(per_serving["fat_g"]))
    recipe.fiber_per_serving_g = Decimal(str(per_serving["fiber_g"]))
    recipe.sodium_per_serving_mg = per_serving["sodium_mg"]
    recipe.nutrition_data = data

    if save:
        recipe.save(update_fields=[
            "calories_per_serving",
            "protein_per_serving_g",
            "carbs_per_serving_g",
            "fat_per_serving_g",
            "fiber_per_serving_g",
            "sodium_per_serving_mg",
            "nutrition_data",
        ])

    return data


def filter_recipes_by_nutrition(
    queryset: QuerySet[Recipe] | None = None,
    min_calories: int | None = None,
    max_calories: int | None = None,
    min_protein: float | None = None,
    max_carbs: float | None = None,
    max_fat: float | None = None,
    min_fiber: float | None = None,
    max_sodium: int | None = None,
) -> QuerySet[Recipe]:
    """
    Filter recipes matching specified nutritional criteria.
    """
    qs = queryset if queryset is not None else Recipe.objects.all()

    if min_calories is not None:
        qs = qs.filter(calories_per_serving__gte=min_calories)
    if max_calories is not None:
        qs = qs.filter(calories_per_serving__lte=max_calories)
    if min_protein is not None:
        qs = qs.filter(protein_per_serving_g__gte=min_protein)
    if max_carbs is not None:
        qs = qs.filter(carbs_per_serving_g__lte=max_carbs)
    if max_fat is not None:
        qs = qs.filter(fat_per_serving_g__lte=max_fat)
    if min_fiber is not None:
        qs = qs.filter(fiber_per_serving_g__gte=min_fiber)
    if max_sodium is not None:
        qs = qs.filter(sodium_per_serving_mg__lte=max_sodium)

    return qs


def suggest_recipes_by_macro_goal(
    goal: str,
    limit: int = 6,
    queryset: QuerySet[Recipe] | None = None,
) -> QuerySet[Recipe]:
    """
    Suggest recipes aligned with a nutritional goal (e.g. 'high-protein', 'low-carb', 'keto', 'low-calorie').
    """
    qs = queryset if queryset is not None else Recipe.objects.all()
    goal_clean = goal.lower().strip()

    if goal_clean in ("high-protein", "protein"):
        return qs.filter(protein_per_serving_g__gte=20).order_by("-protein_per_serving_g")[:limit]
    if goal_clean in ("low-carb", "low-carbohydrate"):
        return qs.filter(calories_per_serving__gt=0, carbs_per_serving_g__lte=25).order_by("carbs_per_serving_g")[:limit]
    if goal_clean in ("keto", "ketogenic"):
        return qs.filter(calories_per_serving__gt=0, carbs_per_serving_g__lte=15, fat_per_serving_g__gte=15).order_by("-fat_per_serving_g")[:limit]
    if goal_clean in ("low-calorie", "light"):
        return qs.filter(calories_per_serving__gt=0, calories_per_serving__lte=400).order_by("calories_per_serving")[:limit]
    if goal_clean in ("balanced",):
        return qs.filter(calories_per_serving__gt=0, calories_per_serving__lte=650, protein_per_serving_g__gte=15).order_by("-protein_per_serving_g")[:limit]

    return qs.filter(calories_per_serving__gt=0).order_by("-protein_per_serving_g")[:limit]


def backfill_all_recipes_nutrition() -> int:
    """
    Compute and update nutritional analysis for all recipes in the database.

    Returns:
        The number of recipes successfully updated.
    """
    count = 0
    recipes = Recipe.objects.prefetch_related("ingredients").all()
    for recipe in recipes:
        try:
            update_recipe_nutrition(recipe, save=True)
            count += 1
        except Exception as exc:
            logger.error("Error computing nutrition for recipe '%s': %s", recipe.name, exc)
    return count
