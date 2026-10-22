"""
Comprehensive culinary inflection, unit conversion, and fraction formatting engine.

Handles singularization and pluralization of grocery items and measurement units,
supporting fractions in units (e.g., '1/3 cups'), culinary exceptions (e.g. 'cloves' -> 'clove',
'slices' -> 'slice', 'loaves' -> 'loaf'), mass/uncountable nouns (e.g. 'asparagus', 'pasta', 'molasses'),
and unit conversions (e.g., '1 pint + 1 pint = 1 quart', '16 oz = 1 lb').
"""

import re
from decimal import Decimal
from fractions import Fraction
from typing import Any

import inflection

# Common words not handled correctly by standard inflection libraries
ITEM_SINGULAR_EXCEPTIONS: dict[str, str] = {
    # Irregular culinary nouns
    "cloves": "clove",
    "slices": "slice",
    "slice": "slice",
    "loaves": "loaf",
    "leaves": "leaf",
    "halves": "half",
    "chilies": "chili",
    "chilis": "chili",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "cherries": "cherry",
    "berries": "berry",
    "strawberries": "strawberry",
    "blueberries": "blueberry",
    "raspberries": "raspberry",
    "blackberries": "blackberry",
    "avocados": "avocado",
    "mangoes": "mango",
    "radishes": "radish",
    "squashes": "squash",
    "zucchinis": "zucchini",
    "bunches": "bunch",
    "heads": "head",
    "ribs": "rib",
    "stalks": "stalk",
    "sprigs": "sprig",
    "ears": "ear",
    "pinches": "pinch",
    "dashes": "dash",
    "cans": "can",
    "boxes": "box",
    "jars": "jar",
    "bottles": "bottle",
    "packages": "package",
    "pieces": "piece",
    "cookies": "cookie",
    "crackers": "cracker",
    "chips": "chip",
    # Measurement units
    "quarts": "quart",
    "pints": "pint",
    "cups": "cup",
    "gallons": "gallon",
    "ounces": "ounce",
    "pounds": "pound",
    "tablespoons": "tablespoon",
    "teaspoons": "teaspoon",
    "grams": "gram",
    "kilograms": "kilogram",
    "milliliters": "milliliter",
    "liters": "liter",
}

ITEM_PLURAL_EXCEPTIONS: dict[str, str] = {
    "clove": "cloves",
    "slice": "slices",
    "loaf": "loaves",
    "leaf": "leaves",
    "half": "halves",
    "chili": "chilies",
    "radish": "radishes",
    "squash": "squashes",
    "potato": "potatoes",
    "tomato": "tomatoes",
    "cherry": "cherries",
    "berry": "berries",
    "strawberry": "strawberries",
    "blueberry": "blueberries",
    "raspberry": "raspberries",
    "blackberry": "blackberries",
    "avocado": "avocados",
    "mango": "mangoes",
    "bunch": "bunches",
    "head": "heads",
    "rib": "ribs",
    "stalk": "stalks",
    "sprig": "sprigs",
    "ear": "ears",
    "pinch": "pinches",
    "dash": "dashes",
    "box": "boxes",
    "package": "packages",
    "piece": "pieces",
    "cookie": "cookies",
    "cracker": "crackers",
    "chip": "chips",
}

# Uncountable/mass nouns that should never be singularized or pluralized into corrupted forms
UNCOUNTABLE_FOODS: set[str] = {
    "asparagus",
    "molasses",
    "hummus",
    "couscous",
    "citrus",
    "pasta",
    "pastas",
    "rice",
    "flour",
    "sugar",
    "salt",
    "pepper",
    "corn",
    "popcorn",
    "broccoli",
    "celery",
    "garlic",
    "ginger",
    "lettuce",
    "spinach",
    "kale",
    "spaghetti",
    "macaroni",
    "penne",
    "fusilli",
    "linguine",
    "fettuccine",
    "gnocchi",
    "ravioli",
    "tortellini",
    "lasagna",
    "lasagne",
    "bacon",
    "tofu",
    "beef",
    "pork",
    "chicken",
    "lamb",
    "fish",
    "salmon",
    "tuna",
    "trout",
    "oats",
    "rolled oats",
    "quinoa",
    "butter",
    "margarine",
    "mayonnaise",
    "mustard",
    "ketchup",
    "honey",
    "syrup",
    "vinegar",
    "oil",
}

# Unit abbreviations that should not take trailing 's' when pluralized
INVARIANT_UNITS: tuple[str, ...] = (
    "oz", "tsp", "tbsp", "lb", "lbs", "c", "C", "qt", "fl oz", "fl. oz",
    "doz", "pt", "pkg", "ml", "l", "L", "gal", "g", "kg", "t", "T"
)


def singularize(word: str) -> str:
    """
    Convert a word or grocery item phrase to its singular form with culinary corrections.

    Handles fractions in units (e.g. '1/3 cups' -> '1/3 cup'), phrases with 'of'
    (e.g. 'cloves of garlic' -> 'clove of garlic'), and mass food nouns.

    Args:
        word: Input word or phrase.

    Returns:
        Singular form of the word.
    """
    if not word:
        return ""

    clean = word.strip()
    lower = clean.lower()

    # 1. Check uncountable / mass nouns
    if lower in UNCOUNTABLE_FOODS:
        return clean

    # 2. Check fractional prefix (e.g. '1/3 cups', '1/2 slices')
    fraction_prefix_match = re.match(r"^(\d+/\d+|\d+\s+\d+/\d+)\s+(.+)$", clean)
    if fraction_prefix_match:
        fraction_str = fraction_prefix_match.group(1)
        sub_word = fraction_prefix_match.group(2)
        return f"{fraction_str} {singularize(sub_word)}"

    # 3. Check 'X of Y' phrases (e.g. 'cloves of garlic', 'heads of lettuce')
    of_match = re.match(r"^(.+)\s+of\s+(.+)$", clean, re.IGNORECASE)
    if of_match:
        head_noun = of_match.group(1)
        tail = of_match.group(2)
        return f"{singularize(head_noun)} of {tail}"

    # 4. Check explicit singular dictionary
    if lower in ITEM_SINGULAR_EXCEPTIONS:
        replacement = ITEM_SINGULAR_EXCEPTIONS[lower]
        if clean.istitle():
            return replacement.title()
        if clean.isupper():
            return replacement.upper()
        return replacement

    # 5. Invariant abbreviations
    if lower in [u.lower() for u in INVARIANT_UNITS]:
        if lower == "lbs":
            return "lb"
        return clean

    result = inflection.singularize(clean)
    # Guard against inflection producing corruptions
    if result.lower() in ("clofe", "slouse", "pastum", "asparagu", "molass", "hummu", "couscou", "citru", "chily", "loafe", "leafe"):
        return ITEM_SINGULAR_EXCEPTIONS.get(lower, clean)

    return result


def pluralize(word: str) -> str:
    """
    Convert a word or grocery item phrase to its plural form with culinary corrections.

    Handles invariant abbreviations, fractions in units (e.g. '1/3 cup' -> '1/3 cups'),
    phrases with 'of' (e.g. 'clove of garlic' -> 'cloves of garlic'), and mass nouns.

    Args:
        word: Input word or phrase.

    Returns:
        Plural form of the word.
    """
    if not word:
        return ""

    clean = word.strip()
    lower = clean.lower()

    # 1. Invariant unit abbreviations (oz, tsp, lb, etc.)
    if lower in [u.lower() for u in INVARIANT_UNITS]:
        return clean

    # 2. Uncountable food nouns (asparagus, pasta, rice, etc.)
    if lower in UNCOUNTABLE_FOODS:
        return clean

    # 3. Fractional prefix (e.g. '1/3 cup' -> '1/3 cups')
    fraction_prefix_match = re.match(r"^(\d+/\d+|\d+\s+\d+/\d+)\s+(.+)$", clean)
    if fraction_prefix_match:
        fraction_str = fraction_prefix_match.group(1)
        sub_word = fraction_prefix_match.group(2)
        return f"{fraction_str} {pluralize(sub_word)}"

    # 4. 'X of Y' phrases (e.g. 'clove of garlic' -> 'cloves of garlic')
    of_match = re.match(r"^(.+)\s+of\s+(.+)$", clean, re.IGNORECASE)
    if of_match:
        head_noun = of_match.group(1)
        tail = of_match.group(2)
        return f"{pluralize(head_noun)} of {tail}"

    # 5. Explicit plural dictionary
    if lower in ITEM_PLURAL_EXCEPTIONS:
        replacement = ITEM_PLURAL_EXCEPTIONS[lower]
        if clean.istitle():
            return replacement.title()
        if clean.isupper():
            return replacement.upper()
        return replacement

    result = inflection.pluralize(clean)
    return result


def singularize_unit(unit: str) -> str:
    """
    Singularize a measurement unit, handling fractional units like '1/3 cups' -> '1/3 cup'.
    """
    return singularize(unit)


def pluralize_unit(unit: str) -> str:
    """
    Pluralize a measurement unit, handling fractional units like '1/3 cup' -> '1/3 cups'.
    """
    return pluralize(unit)


# --- Unit Conversion & Arithmetic ---

# Ratio definitions in base units
VOLUME_UNITS_IN_TSP: dict[str, float] = {
    # Teaspoons
    "tsp": 1.0,
    "teaspoon": 1.0,
    "teaspoons": 1.0,
    "t": 1.0,
    # Tablespoons (1 tbsp = 3 tsp)
    "tbsp": 3.0,
    "tablespoon": 3.0,
    "tablespoons": 3.0,
    "T": 3.0,
    # Fluid ounces (1 fl oz = 6 tsp = 2 tbsp)
    "fl oz": 6.0,
    "fl. oz": 6.0,
    "fluid ounce": 6.0,
    "fluid ounces": 6.0,
    # Cups (1 cup = 48 tsp = 16 tbsp = 8 fl oz)
    "cup": 48.0,
    "cups": 48.0,
    "c": 48.0,
    "C": 48.0,
    # Pints (1 pint = 96 tsp = 2 cups)
    "pint": 96.0,
    "pints": 96.0,
    "pt": 96.0,
    "pts": 96.0,
    # Quarts (1 quart = 192 tsp = 2 pints = 4 cups)
    "quart": 192.0,
    "quarts": 192.0,
    "qt": 192.0,
    "qts": 192.0,
    # Gallons (1 gallon = 768 tsp = 4 quarts = 8 pints = 16 cups)
    "gallon": 768.0,
    "gallons": 768.0,
    "gal": 768.0,
    "gals": 768.0,
}

WEIGHT_US_IN_OZ: dict[str, float] = {
    "oz": 1.0,
    "ounce": 1.0,
    "ounces": 1.0,
    "lb": 16.0,
    "lbs": 16.0,
    "pound": 16.0,
    "pounds": 16.0,
}

WEIGHT_METRIC_IN_G: dict[str, float] = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilograms": 1000.0,
}

VOLUME_METRIC_IN_ML: dict[str, float] = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "l": 1000.0,
    "L": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
}


def parse_fractional_unit(unit_str: str) -> tuple[float, str]:
    """
    Parse units with leading fractions (e.g. '1/3 cup' -> (1/3, 'cup'), '1/2 slice' -> (0.5, 'slice')).

    Args:
        unit_str: Input unit string.

    Returns:
        tuple of (multiplier as float, base unit string).
    """
    clean = unit_str.strip()
    fraction_match = re.match(r"^(\d+/\d+|\d+\s+\d+/\d+)\s+(.+)$", clean)
    if fraction_match:
        frac_text = fraction_match.group(1)
        base_unit = fraction_match.group(2).strip()
        parts = frac_text.split()
        if len(parts) == 2:
            multiplier = float(int(parts[0]) + Fraction(parts[1]))
        else:
            multiplier = float(Fraction(parts[0]))
        return multiplier, base_unit
    return 1.0, clean


def get_unit_family(unit_str: str) -> tuple[str | None, float, bool]:
    """
    Determine the measurement family and base unit scale factor for a unit string.

    Returns:
        tuple of (family_name, scale_to_base, is_abbreviation).
    """
    clean = unit_str.strip()
    if not clean:
        return None, 1.0, False

    multiplier, base_unit = parse_fractional_unit(clean)
    base_lower = base_unit.lower()

    is_abbr = base_lower in ("tsp", "t", "tbsp", "t", "fl oz", "fl. oz", "c", "pt", "qt", "gal", "oz", "lb", "lbs", "g", "kg", "ml", "l")

    if base_lower in VOLUME_UNITS_IN_TSP:
        return "volume_us", VOLUME_UNITS_IN_TSP[base_lower] * multiplier, is_abbr
    if base_lower in WEIGHT_US_IN_OZ:
        return "weight_us", WEIGHT_US_IN_OZ[base_lower] * multiplier, is_abbr
    if base_lower in WEIGHT_METRIC_IN_G:
        return "weight_metric", WEIGHT_METRIC_IN_G[base_lower] * multiplier, is_abbr
    if base_lower in VOLUME_METRIC_IN_ML:
        return "volume_metric", VOLUME_METRIC_IN_ML[base_lower] * multiplier, is_abbr

    return None, multiplier, False


def can_combine_units(unit1: str, unit2: str) -> bool:
    """
    Determine whether two measurement units are compatible and can be combined.

    Units can combine if they are identical (singularized), or if both belong to the same
    convertible measurement system (e.g. pints and quarts, ounces and pounds).
    """
    u1_clean = unit1.strip()
    u2_clean = unit2.strip()

    if not u1_clean and not u2_clean:
        return True
    if not u1_clean or not u2_clean:
        return False

    if singularize(u1_clean.lower()) == singularize(u2_clean.lower()):
        return True

    fam1, _, _ = get_unit_family(u1_clean)
    fam2, _, _ = get_unit_family(u2_clean)

    if fam1 is not None and fam1 == fam2:
        return True

    return False


def combine_amounts_and_units(
    amount1: Decimal | float | int,
    unit1: str,
    amount2: Decimal | float | int,
    unit2: str,
) -> tuple[Decimal, str]:
    """
    Combine two quantities and their measurement units, converting up to natural units.

    Examples:
    - 1 pint + 1 pint = 1 quart
    - 1 pt + 1 pt = 1 qt
    - 2 quarts + 2 quarts = 1 gallon
    - 1/3 cup + 1/3 cup = 2/3 cup
    - 2/3 cup + 1/3 cup = 1 cup
    - 8 oz + 8 oz = 1 lb
    - 500 g + 500 g = 1 kg

    Args:
        amount1: First quantity.
        unit1: First unit.
        amount2: Second quantity.
        unit2: Second unit.

    Returns:
        tuple of (new_amount as Decimal, new_unit as str).
    """
    amt1 = float(amount1)
    amt2 = float(amount2)
    u1_clean = unit1.strip()
    u2_clean = unit2.strip()

    # Both empty units (pure counts, e.g. 2 bananas + 3 bananas = 5 bananas)
    if not u1_clean and not u2_clean:
        return Decimal(str(amt1 + amt2)).quantize(Decimal("0.01")), ""

    fam1, scale1, is_abbr1 = get_unit_family(u1_clean)
    fam2, scale2, is_abbr2 = get_unit_family(u2_clean)
    prefer_abbr = is_abbr1 or is_abbr2

    # Check US Volume (tsp, tbsp, fl oz, cup, pint, quart, gallon)
    if fam1 == "volume_us" and fam2 == "volume_us":
        total_tsp = (amt1 * scale1) + (amt2 * scale2)

        # 1 gallon = 768 tsp (4 quarts)
        if total_tsp >= 768.0 and (total_tsp % 768.0 == 0 or total_tsp >= 1536.0):
            gallons = round(total_tsp / 768.0, 2)
            unit_name = "gal" if prefer_abbr else ("gallon" if gallons == 1 else "gallons")
            return Decimal(str(gallons)).quantize(Decimal("0.01")), unit_name

        # 1 quart = 192 tsp (2 pints)
        # e.g. 1 pint + 1 pint = 2 pints = 192 tsp = 1 quart!
        if total_tsp >= 192.0:
            quarts = round(total_tsp / 192.0, 2)
            # If it's a clean multiple of quarts or > 1 quart
            if quarts.is_integer() or total_tsp >= 192.0:
                unit_name = "qt" if prefer_abbr else ("quart" if quarts == 1 else "quarts")
                return Decimal(str(quarts)).quantize(Decimal("0.01")), unit_name

        # 1 pint = 96 tsp (2 cups)
        # e.g. 1 cup + 1 cup = 2 cups = 96 tsp = 1 pint!
        if total_tsp >= 96.0:
            pints = round(total_tsp / 96.0, 2)
            unit_name = "pt" if prefer_abbr else ("pint" if pints == 1 else "pints")
            return Decimal(str(pints)).quantize(Decimal("0.01")), unit_name

        # 1 cup = 48 tsp (16 tbsp = 8 fl oz)
        # Handles fractional cups (e.g. 1/3 cup + 1/3 cup = 2/3 cup, 2/3 cup + 1/3 cup = 1 cup)
        if total_tsp >= 16.0:
            cups = round(total_tsp / 48.0, 2)
            unit_name = "c" if prefer_abbr else ("cup" if cups == 1 else "cups")
            return Decimal(str(cups)).quantize(Decimal("0.01")), unit_name

        # 1 tbsp = 3 tsp
        if total_tsp >= 3.0 and total_tsp % 3.0 == 0:
            tbsp = round(total_tsp / 3.0, 2)
            unit_name = "tbsp" if prefer_abbr else ("tablespoon" if tbsp == 1 else "tablespoons")
            return Decimal(str(tbsp)).quantize(Decimal("0.01")), unit_name

        unit_name = "tsp" if prefer_abbr else ("teaspoon" if total_tsp == 1 else "teaspoons")
        return Decimal(str(round(total_tsp, 2))).quantize(Decimal("0.01")), unit_name

    # Check US Weight (oz, lb)
    if fam1 == "weight_us" and fam2 == "weight_us":
        total_oz = (amt1 * scale1) + (amt2 * scale2)
        # 16 oz = 1 lb (e.g. 8 oz + 8 oz = 1 lb)
        if total_oz >= 16.0:
            lbs = round(total_oz / 16.0, 2)
            unit_name = "lb" if prefer_abbr else ("pound" if lbs == 1 else "pounds")
            return Decimal(str(lbs)).quantize(Decimal("0.01")), unit_name

        unit_name = "oz" if prefer_abbr else ("ounce" if total_oz == 1 else "ounces")
        return Decimal(str(round(total_oz, 2))).quantize(Decimal("0.01")), unit_name

    # Check Metric Weight (g, kg)
    if fam1 == "weight_metric" and fam2 == "weight_metric":
        total_g = (amt1 * scale1) + (amt2 * scale2)
        if total_g >= 1000.0:
            kgs = round(total_g / 1000.0, 2)
            unit_name = "kg" if prefer_abbr else ("kilogram" if kgs == 1 else "kilograms")
            return Decimal(str(kgs)).quantize(Decimal("0.01")), unit_name

        unit_name = "g" if prefer_abbr else ("gram" if total_g == 1 else "grams")
        return Decimal(str(round(total_g, 2))).quantize(Decimal("0.01")), unit_name

    # Check Metric Volume (ml, l)
    if fam1 == "volume_metric" and fam2 == "volume_metric":
        total_ml = (amt1 * scale1) + (amt2 * scale2)
        if total_ml >= 1000.0:
            liters = round(total_ml / 1000.0, 2)
            unit_name = "l" if prefer_abbr else ("liter" if liters == 1 else "liters")
            return Decimal(str(liters)).quantize(Decimal("0.01")), unit_name

        unit_name = "ml" if prefer_abbr else ("milliliter" if total_ml == 1 else "milliliters")
        return Decimal(str(round(total_ml, 2))).quantize(Decimal("0.01")), unit_name

    # Units with explicit fraction (e.g. unit1 = '1/3 cup', unit2 = '1/3 cup')
    mult1, base1 = parse_fractional_unit(u1_clean)
    mult2, base2 = parse_fractional_unit(u2_clean)
    if singularize(base1.lower()) == singularize(base2.lower()):
        total_base = (amt1 * mult1) + (amt2 * mult2)
        # If total cleanly converts to a whole number of base units
        if total_base.is_integer() or mult1 != 1.0 or mult2 != 1.0:
            base_singular = singularize(base1)
            target_unit = base_singular if total_base == 1.0 else pluralize(base_singular)
            return Decimal(str(round(total_base, 2))).quantize(Decimal("0.01")), target_unit

    # Identical / fallback units
    total_amount = amt1 + amt2
    base_unit = singularize(u1_clean) if u1_clean else singularize(u2_clean)
    target_unit = base_unit if total_amount == 1.0 else pluralize(base_unit)
    return Decimal(str(round(total_amount, 2))).quantize(Decimal("0.01")), target_unit


def format_amount(amount: Any) -> str:
    """
    Format a Decimal or float amount as a clean fraction or whole number string.

    Examples:
    - 0.33 -> '1/3'
    - 0.67 -> '2/3'
    - 0.5 -> '1/2'
    - 0.25 -> '1/4'
    - 0.75 -> '3/4'
    - 1.5 -> '1 1/2'
    - 1.33 -> '1 1/3'
    - 2.00 -> '2'

    Args:
        amount: Quantity as Decimal, float, or int.

    Returns:
        Formatted string representation.
    """
    if amount is None or amount == "":
        return "1"

    try:
        val = float(amount)
    except (ValueError, TypeError):
        return str(amount)

    # Exact integers
    if val.is_integer():
        return str(int(val))

    whole = int(val)
    remainder = round(val - whole, 2)

    fraction_map = {
        0.13: "1/8",
        0.25: "1/4",
        0.33: "1/3",
        0.38: "3/8",
        0.50: "1/2",
        0.63: "5/8",
        0.67: "2/3",
        0.75: "3/4",
        0.88: "7/8",
    }

    # Find closest fraction match within 0.025 tolerance
    closest_fraction = None
    min_diff = 0.025
    for target_rem, frac_str in fraction_map.items():
        diff = abs(remainder - target_rem)
        if diff <= min_diff:
            min_diff = diff
            closest_fraction = frac_str

    if closest_fraction:
        if whole > 0:
            return f"{whole} {closest_fraction}"
        return closest_fraction

    # Fallback to stripped decimal string
    return str(round(val, 2)).rstrip("0").rstrip(".")


def is_quantity_increased(
    amount1: Decimal | float | int,
    unit1: str,
    amount2: Decimal | float | int,
    unit2: str,
) -> bool:
    """
    Check if (amount2, unit2) represents an increase over (amount1, unit1).

    Handles compatible unit families (e.g. 1 pint to 1 quart is an increase,
    while 2 quarts to 1 pint is a decrease). If units are identical or without
    a family, compares amount directly. If the unit itself changed to a different
    measurement, considers it an increase/alteration requiring pantry re-confirmation.

    Args:
        amount1: Original quantity.
        unit1: Original unit string.
        amount2: New/edited quantity.
        unit2: New/edited unit string.

    Returns:
        True if the quantity/unit was increased, False otherwise.
    """
    u1_clean = unit1.strip()
    u2_clean = unit2.strip()

    fam1, scale1, _ = get_unit_family(u1_clean)
    fam2, scale2, _ = get_unit_family(u2_clean)

    if fam1 is not None and fam1 == fam2:
        val1 = float(amount1) * scale1
        val2 = float(amount2) * scale2
        return val2 > val1

    if singularize(u1_clean.lower()) == singularize(u2_clean.lower()):
        return Decimal(str(amount2)) > Decimal(str(amount1))

    # If amount increased directly
    if Decimal(str(amount2)) > Decimal(str(amount1)):
        return True

    # If unit changed to something else
    if u1_clean.lower() != u2_clean.lower():
        return True

    return False

