"""
Service for scraping third-party web recipes and importing them into Shoppin.

Leverages recipe-scrapers and Schema.org Recipe metadata (JSON-LD / microdata)
to extract recipe title, description, timings, yield, photo, instructions,
and structured ingredients with amounts, units, and categories.
"""

import json
import logging
import re
from decimal import Decimal
from fractions import Fraction
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_html

from apps.core.categorizer import categorizer
from apps.recipes.models import Ingredient, Recipe

logger = logging.getLogger(__name__)

# Standard kitchen units for ingredient tokenization
UNITS: set[str] = {
    # Volume
    "cup", "cups", "c",
    "tbsp", "tablespoon", "tablespoons", "tbs", "tb",
    "tsp", "teaspoon", "teaspoons",
    "fl oz", "fluid ounce", "fluid ounces",
    "pt", "pint", "pints",
    "qt", "quart", "quarts",
    "gal", "gallon", "gallons",
    "ml", "milliliter", "milliliters",
    "l", "liter", "liters",
    # Weight
    "oz", "ounce", "ounces",
    "lb", "lbs", "pound", "pounds",
    "g", "gram", "grams",
    "kg", "kilogram", "kilograms",
    # Items & Containers
    "can", "cans",
    "clove", "cloves",
    "bunch", "bunches",
    "package", "packages", "pkg", "pkgs",
    "pinch", "pinches",
    "dash", "dashes",
    "slice", "slices",
    "piece", "pieces",
    "stalk", "stalks",
    "head", "heads",
    "sprig", "sprigs",
    "bottle", "bottles",
    "jar", "jars",
    "box", "boxes",
    "bag", "bags",
    "stick", "sticks",
    "container", "containers",
    "sheet", "sheets",
}

UNICODE_FRACTIONS: dict[str, str] = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_ingredient_line(line: str) -> dict[str, Any]:
    """
    Parse a free-form recipe ingredient text line into structured amount, unit, and name.

    Examples:
        '2 cups all-purpose flour' -> amount: 2.00, amount_unit: 'cups', name: 'all-purpose flour'
        '1/2 tsp kosher salt'      -> amount: 0.50, amount_unit: 'tsp',  name: 'kosher salt'
        '3 ripe avocados'          -> amount: 3.00, amount_unit: '',     name: 'ripe avocados'

    Args:
        line: Raw ingredient text string.

    Returns:
        Dict with amount (Decimal), amount_unit (str), name (str), and category (str).
    """
    text = line.strip()
    for u_char, f_str in UNICODE_FRACTIONS.items():
        text = text.replace(u_char, f" {f_str} ")
    text = re.sub(r"\s+", " ", text).strip()

    amount = Decimal("1.00")
    unit = ""
    name = text
    rest = text

    # Pattern 1: Mixed fraction, e.g. "1 1/2" or "1-1/2"
    mixed_m = re.match(r"^(\d+)(?:[\s\-]+)(\d+/\d+)\s*(.*)$", text)
    if mixed_m:
        whole = int(mixed_m.group(1))
        frac = Fraction(mixed_m.group(2))
        amount = Decimal(str(float(whole + frac))).quantize(Decimal("0.01"))
        rest = mixed_m.group(3).strip()
    else:
        # Pattern 2: Simple fraction, e.g. "1/2"
        frac_m = re.match(r"^(\d+/\d+)\s*(.*)$", text)
        if frac_m:
            frac = Fraction(frac_m.group(1))
            amount = Decimal(str(float(frac))).quantize(Decimal("0.01"))
            rest = frac_m.group(2).strip()
        else:
            # Pattern 3: Range: "1-2" or "1 to 2" -> pick first
            range_m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(.*)$", text, re.IGNORECASE)
            if range_m:
                amount = Decimal(range_m.group(1)).quantize(Decimal("0.01"))
                rest = range_m.group(2).strip()
            else:
                # Pattern 4: Decimal or integer: "3" or "2.5"
                num_m = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", text)
                if num_m:
                    amount = Decimal(num_m.group(1)).quantize(Decimal("0.01"))
                    rest = num_m.group(2).strip()
                else:
                    rest = text

    # Check multi-word units first (e.g. "fluid ounces", "fl oz")
    multi_units = [("fluid ounces", 2), ("fluid ounce", 2), ("fl oz", 2)]
    matched_unit = False
    for uc, _ in multi_units:
        if rest.lower().startswith(uc + " "):
            unit = uc
            name = rest[len(uc):].strip()
            matched_unit = True
            break

    # Handle parenthesized unit sizes, e.g. "(15-ounce) can black beans"
    if not matched_unit:
        paren_m = re.match(r"^(\([^)]*\))\s+(.*)$", rest)
        if paren_m:
            paren = paren_m.group(1)
            after_paren = paren_m.group(2)
            parts = after_paren.split(" ", 1)
            first_word = parts[0].lower().rstrip(".,")
            if first_word in UNITS:
                unit = parts[0].rstrip(".,")
                name = f"{paren} {parts[1]}" if len(parts) > 1 else paren
                matched_unit = True

    # Check single-word units
    if not matched_unit:
        parts = rest.split(" ", 1)
        first_word = parts[0].lower().rstrip(".,")
        if first_word in UNITS:
            unit = parts[0].rstrip(".,")
            name = parts[1].strip() if len(parts) > 1 else ""
        else:
            name = rest

    # Remove leading "of " e.g. "cups of sugar" -> "sugar"
    if name.lower().startswith("of "):
        name = name[3:].strip()

    final_name = name if name else line
    return {
        "raw": line,
        "amount": amount,
        "amount_unit": unit,
        "name": final_name,
        "category": categorizer.get_category(final_name),
    }


def _safe_call(func, default=None):
    """Execute a scraper accessor method safely returning default on failure."""
    try:
        val = func()
        return val if val is not None else default
    except Exception:
        return default


def normalize_url(url: str) -> str:
    """Ensure URL has a valid scheme (defaults to https://)."""
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


def scrape_recipe_data(url: str, html: str | None = None) -> dict[str, Any]:
    """
    Fetch and parse recipe details from any third-party webpage.

    Uses recipe-scrapers with supported_only=False (supporting hundreds of specific sites
    and generic Schema.org Recipe markup), with BeautifulSoup JSON-LD fallbacks.

    Args:
        url: The webpage URL.
        html: Optional raw HTML string (for testing or cached pages).

    Returns:
        Structured dict with name, description, directions, portions, prep_time,
        cook_time, photo_url, cuisine, dish_type, and parsed ingredients.

    Raises:
        ValueError: If no recipe information could be detected on the page.
    """
    url = normalize_url(url)
    domain = urlparse(url).netloc.lower()

    if html is None:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.error("Failed to fetch recipe webpage '%s': %s", url, exc)
            raise ValueError(f"Could not connect to or retrieve webpage: {exc}") from exc

    # 1. Attempt parsing via recipe-scrapers
    scraper = None
    try:
        scraper = scrape_html(html, org_url=url, supported_only=False)
    except Exception as exc:
        logger.warning("recipe-scrapers could not initialize on '%s': %s", url, exc)

    name = ""
    description = ""
    raw_ingredients: list[str] = []
    instructions = ""
    yields_val = ""
    prep_time = 0
    cook_time = 0
    total_time = 0
    photo_url = ""
    cuisine = ""
    dish_type = ""

    if scraper:
        name = _safe_call(scraper.title, "") or ""
        description = _safe_call(scraper.description, "") or ""
        raw_ingredients = _safe_call(scraper.ingredients, []) or []
        instructions = _safe_call(scraper.instructions, "") or ""
        yields_val = _safe_call(scraper.yields, "") or ""
        prep_time = int(_safe_call(scraper.prep_time, 0) or 0)
        cook_time = int(_safe_call(scraper.cook_time, 0) or 0)
        total_time = int(_safe_call(scraper.total_time, 0) or 0)
        photo_url = _safe_call(scraper.image, "") or ""
        cuisine = _safe_call(scraper.cuisine, "") or ""
        dish_type = _safe_call(scraper.category, "") or ""

    # 2. Fallback to manual Schema.org Recipe extraction if title or ingredients are empty
    if not name or not raw_ingredients:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                if not script.string:
                    continue
                try:
                    data = json.loads(script.string)
                except Exception:
                    continue

                candidates = []
                if isinstance(data, list):
                    candidates = data
                elif isinstance(data, dict):
                    if "@graph" in data and isinstance(data["@graph"], list):
                        candidates = data["@graph"]
                    else:
                        candidates = [data]

                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("@type", "")
                    is_recipe = (item_type == "Recipe") or (isinstance(item_type, list) and "Recipe" in item_type)
                    if is_recipe:
                        if not name:
                            name = item.get("name", "")
                        if not description:
                            description = item.get("description", "")
                        if not raw_ingredients and "recipeIngredient" in item:
                            raw_ingredients = item.get("recipeIngredient", [])
                        if not photo_url and "image" in item:
                            img = item.get("image")
                            if isinstance(img, str):
                                photo_url = img
                            elif isinstance(img, list) and img and isinstance(img[0], str):
                                photo_url = img[0]
                            elif isinstance(img, dict) and "url" in img:
                                photo_url = img["url"]
                        if not instructions and "recipeInstructions" in item:
                            inst = item.get("recipeInstructions")
                            if isinstance(inst, str):
                                instructions = inst
                            elif isinstance(inst, list):
                                steps = []
                                for step in inst:
                                    if isinstance(step, str):
                                        steps.append(step)
                                    elif isinstance(step, dict) and "text" in step:
                                        steps.append(step["text"])
                                instructions = "\n".join(steps)
                        break
        except Exception as exc:
            logger.warning("Manual JSON-LD fallback parsing failed on '%s': %s", url, exc)

    if not name and not raw_ingredients:
        raise ValueError(
            f"No recipe data (ingredients or title) could be detected at '{url}'. "
            "Please check that the URL points directly to a page containing a recipe."
        )

    # 3. Clean up and format fields
    portions = 4
    if yields_val:
        num_match = re.search(r"\d+", str(yields_val))
        if num_match:
            portions = max(1, int(num_match.group(0)))

    # Compute cook/prep times if only total is available
    if cook_time == 0 and prep_time == 0 and total_time > 0:
        cook_time = total_time

    # Parse ingredient strings into structured objects
    structured_ingredients = [parse_ingredient_line(line) for line in raw_ingredients if line and str(line).strip()]

    return {
        "name": name.strip() if name else "Imported Recipe",
        "description": description.strip(),
        "directions": instructions.strip(),
        "portions": portions,
        "prep_time_minutes": prep_time,
        "cook_time_minutes": cook_time,
        "photo_url": photo_url.strip(),
        "cuisine": cuisine.strip(),
        "dish_type": dish_type.strip(),
        "ingredients": structured_ingredients,
        "source_url": url,
        "domain": domain,
    }


def import_recipe_from_url(
    url: str,
    user: Any = None,
    html: str | None = None,
) -> Recipe:
    """
    Scrape a third-party webpage and create a new Recipe in the database.

    Args:
        url: Webpage URL to scrape.
        user: Optional creating User model instance.
        html: Optional raw HTML string (useful for offline tests).

    Returns:
        The newly created Recipe instance.
    """
    data = scrape_recipe_data(url=url, html=html)

    # Ensure unique recipe name
    base_name = data["name"]
    final_name = base_name
    counter = 1
    while Recipe.objects.filter(name=final_name).exists():
        final_name = f"{base_name} ({counter})"
        counter += 1

    recipe = Recipe.objects.create(
        name=final_name,
        description=data["description"],
        directions=data["directions"],
        portions=data["portions"],
        prep_time_minutes=data["prep_time_minutes"],
        cook_time_minutes=data["cook_time_minutes"],
        cuisine=data["cuisine"],
        dish_type=data["dish_type"],
        photo_urls=[data["photo_url"]] if data["photo_url"] else [],
        bibliography=[data["source_url"]],
        created_by=user if (user and user.is_authenticated) else None,
    )

    for i, ing_data in enumerate(data["ingredients"]):
        Ingredient.objects.create(
            recipe=recipe,
            name=ing_data["name"],
            amount=ing_data["amount"],
            amount_unit=ing_data["amount_unit"],
            category=ing_data["category"],
            order=i,
        )

    logger.info("Successfully imported recipe '%s' (ID %d) from '%s'", recipe.name, recipe.id, url)
    return recipe
