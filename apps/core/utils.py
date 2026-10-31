"""
Core string parsing, linguistic utility functions, and unit arithmetic.

Provides robust amount and unit extraction from free-form user inputs (e.g. fractions,
word numbers, decimals), culinary-aware singularization and pluralization,
and unit conversions.
"""

import re
from decimal import Decimal
from fractions import Fraction
from typing import Any

from apps.core.units import (
    can_combine_units,
    combine_amounts_and_units,
    format_amount,
    is_quantity_increased,
    parse_fractional_unit,
    pluralize,
    pluralize_unit,
    singularize,
    singularize_unit,
)

WORD_NUMBERS: dict[str, float] = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "dozen": 12.0,
    "half": 0.5,
    "quarter": 0.25,
}


def parse_amount_and_unit(raw_input: Any) -> tuple[Decimal, str]:
    """
    Parse free-form user quantities into a numeric Decimal amount and unit string.

    Supports:
    - Mixed fractions ('1 1/2 cups', '1 1/3 cups')
    - Simple fractions ('1/3 cups', '1/2 cup', '3/4 tsp')
    - Word numbers ('one pint', 'two quarts', 'a gallon', 'half cup')
    - Decimals ('0.5 lbs', '1.25 kg')
    - Plain integers ('2')
    - Default to 1.00 if omitted.

    Args:
        raw_input: Raw string or numeric value provided by user or recipe.

    Returns:
        tuple of (amount as Decimal with 2 decimal places, unit string).
    """
    if raw_input is None or raw_input == "":
        return Decimal("1.00"), ""

    if isinstance(raw_input, (int, float, Decimal)):
        return Decimal(str(raw_input)).quantize(Decimal("0.01")), ""

    clean_text = str(raw_input).strip()
    if not clean_text:
        return Decimal("1.00"), ""

    # Pattern 1: mixed fraction, e.g. "1 1/2 cups", "2 1/3 cups"
    mixed_match = re.match(r"^(\d+)\s+(\d+/\d+)\s*(.*)$", clean_text)
    if mixed_match:
        whole_number = int(mixed_match.group(1))
        fraction_part = Fraction(mixed_match.group(2))
        total_amount = Decimal(str(float(whole_number + fraction_part))).quantize(Decimal("0.01"))
        unit = mixed_match.group(3).strip()
        return total_amount, unit

    # Pattern 2: simple fraction, e.g. "1/3 cups", "1/2 cup", "3/4 tsp"
    fraction_match = re.match(r"^(\d+/\d+)\s*(.*)$", clean_text)
    if fraction_match:
        fraction_part = Fraction(fraction_match.group(1))
        total_amount = Decimal(str(float(fraction_part))).quantize(Decimal("0.01"))
        unit = fraction_match.group(2).strip()
        return total_amount, unit

    # Pattern 3: decimal or integer followed by optional unit, e.g. "1.5 lbs", "2 cans"
    decimal_match = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", clean_text)
    if decimal_match:
        amount_value = Decimal(decimal_match.group(1)).quantize(Decimal("0.01"))
        unit = decimal_match.group(2).strip()
        return amount_value, unit

    # Pattern 4: word numbers, e.g. "one pint", "two quarts", "a cup", "half pint"
    word_match = re.match(r"^([a-zA-Z]+)\s*(.*)$", clean_text)
    if word_match:
        first_word = word_match.group(1).lower()
        remainder = word_match.group(2).strip()
        if first_word in WORD_NUMBERS:
            amount_val = Decimal(str(WORD_NUMBERS[first_word])).quantize(Decimal("0.01"))
            # If word is 'half' or 'quarter' followed by 'a' (e.g. 'half a cup')
            if remainder.lower().startswith("a "):
                remainder = remainder[2:].strip()
            return amount_val, remainder

    # Fallback if no numeric or word prefix was recognized
    return Decimal("1.00"), clean_text


def clean_purpose(value: str | None) -> str:
    """
    Strip repeated leading 'For ' or 'for ' prefixes from a purpose string.

    Args:
        value: Raw purpose string.

    Returns:
        Cleaned purpose string without leading 'For ' prefixes.
    """
    if not value:
        return ""
    val = value.strip()
    while val.lower().startswith("for "):
        val = val[4:].strip()
    return val


COMMON_UNITS: set[str] = {
    "lb", "lbs", "pound", "pounds", "oz", "ounce", "ounces",
    "cup", "cups", "c", "tbsp", "tablespoon", "tablespoons", "tbs",
    "tsp", "teaspoon", "teaspoons", "can", "cans", "clove", "cloves",
    "pinch", "pinches", "slice", "slices", "bunch", "bunches",
    "head", "heads", "bag", "bags", "package", "packages", "pkg", "pkgs",
    "bottle", "bottles", "jar", "jars", "g", "gram", "grams", "kg", "kilogram", "kilograms",
    "ml", "liter", "liters", "l", "qt", "quart", "quarts", "pt", "pint", "pints",
}


def parse_ingredient_line(raw_line: str) -> tuple[str, Decimal, str]:
    """
    Parse a free-form ingredient string (e.g. '2 lbs Roma tomatoes', '1/2 cup olive oil')
    into (name, amount, unit).

    Args:
        raw_line: Raw input string.

    Returns:
        tuple of (clean_name: str, amount: Decimal, unit: str).
    """
    clean = (raw_line or "").strip()
    if not clean:
        return "", Decimal("1.00"), ""

    amt, remainder = parse_amount_and_unit(clean)
    if not remainder:
        return clean, amt, ""

    parts = remainder.split(None, 1)
    first_token = parts[0].lower().rstrip(".,")
    if first_token in COMMON_UNITS:
        unit = parts[0].rstrip(".,")
        name = parts[1].strip() if len(parts) > 1 else ""
        if name:
            return name, amt, unit

    return remainder, amt, ""


_KNOWN_INGREDIENTS_CACHE: list[str] | None = None
_KNOWN_INGREDIENTS_CACHE_TIME: float = 0.0


def get_known_ingredient_suggestions() -> list[str]:
    """
    Return a cached, deduplicated list of known ingredient and grocery item names
    for client-side autocomplete / auto-suggest.
    """
    global _KNOWN_INGREDIENTS_CACHE, _KNOWN_INGREDIENTS_CACHE_TIME
    import time
    now = time.time()
    if _KNOWN_INGREDIENTS_CACHE is not None and (now - _KNOWN_INGREDIENTS_CACHE_TIME) < 60:
        return _KNOWN_INGREDIENTS_CACHE

    from apps.recipes.models import Ingredient
    from apps.shopping.models import ShoppingListItem
    from apps.core.categorizer import categorizer

    names: set[str] = set()
    try:
        names.update(Ingredient.objects.values_list("name", flat=True).distinct())
    except Exception:
        pass
    try:
        names.update(ShoppingListItem.objects.values_list("name", flat=True).distinct())
    except Exception:
        pass
    if categorizer and hasattr(categorizer, "items_index"):
        names.update(categorizer.items_index.keys())

    cleaned = sorted({
        n.strip().title()
        for n in names
        if n and len(n.strip()) > 1 and not n.strip().isdigit() and not n.strip().startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9"))
    })
    _KNOWN_INGREDIENTS_CACHE = cleaned
    _KNOWN_INGREDIENTS_CACHE_TIME = now
    return cleaned


__all__ = [
    "can_combine_units",
    "clean_purpose",
    "combine_amounts_and_units",
    "format_amount",
    "get_known_ingredient_suggestions",
    "is_quantity_increased",
    "parse_amount_and_unit",
    "parse_fractional_unit",
    "parse_ingredient_line",
    "pluralize",
    "pluralize_unit",
    "singularize",
    "singularize_unit",
]
