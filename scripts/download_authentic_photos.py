"""
Download and optimize authentic, matching photos for all recipes in the database
from high-resolution public culinary sources (Wikimedia/Wikipedia).
Resizes and compresses images to 800px JPEG files stored in media/recipes/photos/.
"""

import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from PIL import Image  # noqa: E402

from apps.recipes.models import Recipe  # noqa: E402

PHOTOS_DIR = BASE_DIR / "media" / "recipes" / "photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

RECIPE_WIKI_MAP = {
    "Asian salad": "Chinese_chicken_salad",
    "Banana Treats": "Chocolate-covered_banana",
    "Brisket in the Instant Pot": "Brisket",
    "Corn on the cob": "Corn_on_the_cob",
    "Creamy Corn Casserole": "Corn_pudding",
    "Creamy Mocha Fudge": "Fudge",
    "Crêpes": "Cr%C3%AApe",
    "Eggplant Parmesan": "Parmigiana",
    "Hashbrowns": "Hash_browns",
    "Kale": "Kale",
    "Lasagna": "Lasagna",
    "Monte Christo Sandwich": "Monte_Cristo_sandwich",
    "Morkov-cha Koryo-saram carrot salad": "Morkovcha",
    "PB&J Sandwich": "Peanut_butter_and_jelly_sandwich",
    "Pumkin bean and kale soup": "Pumpkin_soup",
    "Russian Vinigret": "Vinegret",
    "S'mores": "S%27more",
    "Salsa Verde": "Salsa_verde",
    "Soft and Chewy Almond Sugar Cookies": "Sugar_cookie",
    "Soviet 'New Years Clock' Salad": "Mimosa_salad",
    "Soviet Olivier 'Olivye' Salad": "Olivier_salad",
    "Spanish rice": "Spanish_rice",
    "Sweet Potato Casserole": "Sweet_potato",
    "Veggie Pot Pie": "Pot_pie",
    "black bean burger": "Veggie_burger",
    "black bean patty with cheese": "Veggie_burger",
    "buckwheat": "Buckwheat",
    "burger sauce": "Fry_sauce",
    "butternut squash soup": "Pumpkin_soup",
    "buttery lima beans": "Lima_bean",
    "cabbage and egg salad with cucumber": "Coleslaw",
    "canellini bean side dish": "Cannellini",
    "cheesy puff pastry rolls": "B%C3%B6rek",
    "cobb salad": "Cobb_salad",
    "cold borscht": "Cold_borscht",
    "cole slaw": "Coleslaw",
    "collard greens": "Collard_greens",
    "edible chalk sugar candy": "Sugar_candy",
    "egg salad sandwiches": "Egg_salad",
    "esquites": "Esquites",
    "fried egg": "Fried_egg",
    "garlic bread": "Garlic_bread",
    "kale gnocchi": "Gnocchi",
    "kharcho": "Kharcho",
    "lima bean side dish": "Lima_bean",
    "mac-and-cheese casserole": "Macaroni_and_cheese",
    "mashed potatoes": "Mashed_potato",
    "mashed potatoes with herbs": "Mashed_potato",
    "mayo egg": "Oeuf_mayonnaise",
    "meatballs": "Meatball",
    "meatloaf": "Meatloaf",
    "minestrone soup": "Minestrone",
    "pan-fried chicken": "Chicken_cutlet",
    "pancakes": "Pancake",
    "pinto beans": "Pinto_bean",
    "quesadilla": "Quesadilla",
    "quinoa": "Quinoa",
    "quinoa and white bean soup": "Minestrone",
    "refried beans": "Refried_beans",
    "roasted broccoli": "Broccoli",
    "salad with butter lettuce": "Salad",
    "schnitzel": "Schnitzel",
    "sloppy joes": "Sloppy_joe",
    "slow cooked chicken": "Pulled_chicken",
    "slow cooked turkey": "Turkey_meat",
    "smashburgers": "Cheeseburger",
    "solyanka": "Solyanka",
    "spaghetti": "Spaghetti",
    "steak": "Steak",
    "steamed broccoli": "Broccoli",
    "stir fry": "Stir_frying",
    "stir fry beef": "Beef_chow_fun",
    "stuffed shells": "Conchiglie",
    "taco soup": "Tortilla_soup",
    "tacos and burritos": "Taco",
    "tahini miso dressing": "Tahini",
    "take-out": "Take-out",
    "tofu joe": "Tofu",
    "tortellini soup": "Tortellini",
    "twice baked potatoes": "Baked_potato",
    "vanilla pudding": "Pudding",
    "vegetables a la Grecque": "Ratatouille",
    "vegetarian kharcho": "Kharcho",
    "vegetarian zucchini casserole": "Zucchini",
    "veggie nuggets": "Chicken_nugget",
    "zucchini casserole": "Zucchini",
}


def fetch_wiki_image_url(subject: str) -> str | None:
    """Fetch thumbnail image URL from Wikipedia REST API."""
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{subject}"
    req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            thumb = data.get("thumbnail", {}).get("source")
            orig = data.get("originalimage", {}).get("source")
            return thumb or orig
    except Exception as err:
        print(f"  [API Error for {subject}]: {err}")
        return None


def download_and_optimize_image(image_url: str, dest_path: Path) -> bool:
    """Download image, resize with Pillow to max 800x800, and save as JPEG."""
    req = urllib.request.Request(image_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read()
            with Image.open(io.BytesIO(raw_data)) as img:
                img = img.convert("RGB")
                img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                img.save(dest_path, "JPEG", quality=85, optimize=True)
                return True
    except Exception as err:
        print(f"  [Download Error from {image_url[:50]}...]: {err}")
        return False


def main() -> None:
    recipes = Recipe.objects.all().order_by("name")
    print(f"Enriching {recipes.count()} recipes with authentic photos...")

    success_count = 0
    skipped_count = 0

    for recipe in recipes:
        # Check mapping
        lookup_key = recipe.name
        subject = RECIPE_WIKI_MAP.get(lookup_key)

        if not subject:
            # Fallback search by cleaned recipe name
            cleaned = recipe.name.replace(" ", "_")
            subject = urllib.parse.quote(cleaned)

        dest_file = PHOTOS_DIR / f"{recipe.slug}.jpg"

        # Check if already downloaded
        if dest_file.exists() and dest_file.stat().st_size > 1000:
            recipe.photo_file = f"recipes/photos/{dest_file.name}"
            recipe.save(update_fields=["photo_file"])
            skipped_count += 1
            print(f"[{recipe.id}] {recipe.name}: Already exists -> {dest_file.name}")
            continue

        print(f"[{recipe.id}] {recipe.name}: Finding photo for '{subject}'...")
        img_url = fetch_wiki_image_url(subject)
        time.sleep(0.75)

        if not img_url:
            print(f"  -> No photo found for {recipe.name}")
            continue

        ok = download_and_optimize_image(img_url, dest_file)
        time.sleep(0.75)

        if ok:
            recipe.photo_file = f"recipes/photos/{dest_file.name}"
            # Also clear any old mismatched photo_urls so primary_photo_url uses photo_file
            recipe.photo_urls = [recipe.photo_file.url]
            recipe.save(update_fields=["photo_file", "photo_urls"])
            success_count += 1
            print(f"  -> SUCCESS: Saved {dest_file.name} ({dest_file.stat().st_size // 1024} KB)")
        else:
            print(f"  -> FAILED to download for {recipe.name}")

    print(f"\nDone! Successfully updated: {success_count}, Existing: {skipped_count}, Total: {recipes.count()}")


if __name__ == "__main__":
    main()
