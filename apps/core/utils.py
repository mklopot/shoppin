"""
Core string parsing and linguistic utility functions.

Provides robust amount and unit extraction from free-form user inputs (e.g. fractions,
decimals, unit words) as well as culinary-aware singularization and pluralization.
"""

import re
from decimal import Decimal
from fractions import Fraction

import inflection


def parse_amount_and_unit(raw_input: str | int | float | None) -> tuple[Decimal, str]:
    """
    Parse free-form user quantities into a numeric Decimal amount and unit string.

    Supports mixed fractions ('1 1/2 cups'), simple fractions ('1/2 cup'),
    decimals ('0.5 lbs'), plain integers ('2'), and defaults to 1.00 if omitted.

    Args:
        raw_input: Raw string or numeric value provided by user or recipe.

    Returns:
        tuple of (amount as Decimal with 2 decimal places, unit string).
    """
    if raw_input is None or raw_input == "":
        return Decimal("1.00"), ""

    if isinstance(raw_input, (int, float)):
        return Decimal(str(raw_input)).quantize(Decimal("0.01")), ""

    clean_text = str(raw_input).strip()

    # Pattern 1: mixed fraction, e.g. "1 1/2 cups"
    mixed_match = re.match(r"^(\d+)\s+(\d+/\d+)\s*(.*)$", clean_text)
    if mixed_match:
        whole_number = int(mixed_match.group(1))
        fraction_part = Fraction(mixed_match.group(2))
        total_amount = Decimal(str(float(whole_number + fraction_part))).quantize(Decimal("0.01"))
        unit = mixed_match.group(3).strip()
        return total_amount, unit

    # Pattern 2: simple fraction, e.g. "1/2 cup" or "3/4 tsp"
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

    # Fallback if no leading numeric prefix was found
    return Decimal("1.00"), clean_text


def singularize(word: str) -> str:
    """
    Convert a plural word to its singular form, respecting culinary exceptions.

    Args:
        word: The word to singularize (e.g. 'cloves', 'tomatoes').

    Returns:
        The singular word string (e.g. 'clove', 'tomato').
    """
    exceptions = {"cloves": "clove", "slices": "slice"}
    if word in exceptions:
        return exceptions[word]
    return inflection.singularize(word)


def pluralize(word: str) -> str:
    """
    Convert a singular word to its plural form, skipping abbreviation units.

    Args:
        word: The word or unit to pluralize (e.g. 'apple', 'oz').

    Returns:
        The pluralized word string, or unchanged if an invariant unit abbreviation.
    """
    invariant_units = (
        "oz", "tsp", "tbsp", "lb", "c", "qt", "fl oz", "fl. oz",
        "pkg", "ml", "l", "gal", "g", "kg"
    )
    if word.lower() in invariant_units:
        return word
    return inflection.pluralize(word)
