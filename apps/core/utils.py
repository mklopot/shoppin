import re
from decimal import Decimal
from fractions import Fraction

import inflection


def parse_amount_and_unit(raw_str: str | int | float | None) -> tuple[Decimal, str]:
    """
    Parses strings like '1 lb', '0.5', '1/2 cup', '2 cans', '4', 2 into (Decimal, unit).
    """
    if raw_str is None or raw_str == "":
        return Decimal("1.00"), ""

    if isinstance(raw_str, (int, float)):
        return Decimal(str(raw_str)).quantize(Decimal("0.01")), ""

    clean = str(raw_str).strip()

    # Match mixed fraction (e.g. '1 1/2 cups') or simple fraction ('1/2 cup') or decimal/int ('1.5 lbs', '2')
    # Pattern 1: mixed fraction: (\d+)\s+(\d+/\d+)(.*)
    mixed_match = re.match(r"^(\d+)\s+(\d+/\d+)\s*(.*)$", clean)
    if mixed_match:
        whole = int(mixed_match.group(1))
        frac = Fraction(mixed_match.group(2))
        total = Decimal(str(float(whole + frac))).quantize(Decimal("0.01"))
        unit = mixed_match.group(3).strip()
        return total, unit

    # Pattern 2: simple fraction: (\d+/\d+)(.*)
    frac_match = re.match(r"^(\d+/\d+)\s*(.*)$", clean)
    if frac_match:
        frac = Fraction(frac_match.group(1))
        total = Decimal(str(float(frac))).quantize(Decimal("0.01"))
        unit = frac_match.group(2).strip()
        return total, unit

    # Pattern 3: decimal or integer followed by optional unit: (\d+(?:\.\d+)?)\s*(.*)
    dec_match = re.match(r"^(\d+(?:\.\d+)?)\s*(.*)$", clean)
    if dec_match:
        val = Decimal(dec_match.group(1)).quantize(Decimal("0.01"))
        unit = dec_match.group(2).strip()
        return val, unit

    # Fallback if no leading number found
    return Decimal("1.00"), clean


def singularize(word: str) -> str:
    exceptions = {"cloves": "clove", "slices": "slice"}
    if word in exceptions:
        return exceptions[word]
    return inflection.singularize(word)


def pluralize(word: str) -> str:
    exclusions = (
        "oz", "tsp", "tbsp", "lb", "c", "qt", "fl oz", "fl. oz",
        "pkg", "ml", "l", "gal", "g", "kg"
    )
    if word.lower() in exclusions:
        return word
    return inflection.pluralize(word)
