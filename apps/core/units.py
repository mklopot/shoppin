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

_COMPOUND_TAIL_RE = re.compile(
    r"^(.+?)((?:,\s*\d.+?)?\s+and\s+(?:\d|a\b|an\b|one\b|two\b|three\b|four\b|half\b|quarter\b).*)$",
    re.IGNORECASE,
)

_COMPOUND_WORD_NUMS: dict[str, float] = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "half": 0.5,
    "quarter": 0.25,
}


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

    # 2b. Check compound unit tail (e.g. 'gallons and 1 cup' -> 'gallon and 1 cup')
    compound_match = _COMPOUND_TAIL_RE.match(clean)
    if compound_match:
        head_unit, tail_clause = compound_match.group(1).strip(), compound_match.group(2)
        return f"{singularize(head_unit)}{tail_clause}"

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

    # 3b. Check compound unit tail (e.g. 'gallon and 1 cup' -> 'gallons and 1 cup')
    compound_match = _COMPOUND_TAIL_RE.match(clean)
    if compound_match:
        head_unit, tail_clause = compound_match.group(1).strip(), compound_match.group(2)
        return f"{pluralize(head_unit)}{tail_clause}"

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


def _parse_compound_clause(clause: str) -> tuple[float, str] | None:
    """Parse '<number/fraction/word> <unit>' inside a compound unit tail."""
    clean = (clause or "").strip()
    if not clean:
        return None
    m = re.match(r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s+(.+)$", clean)
    if m:
        qty_str, unit_str = m.group(1).strip(), m.group(2).strip()
        parts = qty_str.split()
        try:
            if len(parts) == 2:
                amt = float(int(parts[0]) + Fraction(parts[1]))
            elif "/" in qty_str:
                amt = float(Fraction(qty_str))
            else:
                amt = float(qty_str)
        except (ValueError, ZeroDivisionError):
            return None
        return amt, unit_str

    word_match = re.match(r"^([a-zA-Z]+)\s+(.+)$", clean)
    if word_match:
        w_low = word_match.group(1).lower()
        rest = word_match.group(2).strip()
        if w_low in _COMPOUND_WORD_NUMS and rest:
            if rest.lower().startswith("a "):
                rest = rest[2:].strip()
            return _COMPOUND_WORD_NUMS[w_low], rest
    return None


def _get_single_unit_family(unit_str: str) -> tuple[str | None, float, bool]:
    """Resolve measurement family and base scale factor for a non-compound unit string."""
    clean = (unit_str or "").strip()
    if not clean:
        return None, 1.0, False

    multiplier, base_unit = parse_fractional_unit(clean)
    base_lower = base_unit.lower()
    is_abbr = base_lower in (
        "tsp", "t", "tbsp", "fl oz", "fl. oz", "c", "pt", "qt", "gal",
        "oz", "lb", "lbs", "g", "kg", "ml", "l",
    )

    if base_lower in VOLUME_UNITS_IN_TSP:
        return "volume_us", VOLUME_UNITS_IN_TSP[base_lower] * multiplier, is_abbr
    if base_lower in WEIGHT_US_IN_OZ:
        return "weight_us", WEIGHT_US_IN_OZ[base_lower] * multiplier, is_abbr
    if base_lower in WEIGHT_METRIC_IN_G:
        return "weight_metric", WEIGHT_METRIC_IN_G[base_lower] * multiplier, is_abbr
    if base_lower in VOLUME_METRIC_IN_ML:
        return "volume_metric", VOLUME_METRIC_IN_ML[base_lower] * multiplier, is_abbr

    return None, multiplier, False


def _split_compound_unit(unit_str: str) -> tuple[str, list[str]]:
    """Split compound units like 'gallons, 1 pint and 1 cup' into (head_unit, [tail_clauses])."""
    clean = (unit_str or "").strip()
    if not clean:
        return "", []
    compound_match = _COMPOUND_TAIL_RE.match(clean)
    if not compound_match:
        return clean, []
    head = compound_match.group(1).strip()
    tail_raw = re.sub(r"^(?:,|and)\s*", "", compound_match.group(2).strip(), flags=re.IGNORECASE)
    clauses = [
        p.strip()
        for p in re.split(r"\s+and\s+|,\s*", tail_raw, flags=re.IGNORECASE)
        if p and p.strip()
    ]
    return head, clauses


def to_base_quantity(amount: Decimal | float | int, unit_str: str) -> tuple[str | None, float, bool]:
    """
    Convert a possibly compound quantity like (1, 'gallon and 1 cup') or (2, 'pints')
    into (family_name, total_in_base_units, is_abbreviated).
    """
    head, tail_clauses = _split_compound_unit(unit_str)
    fam, scale, is_abbr = _get_single_unit_family(head)
    if fam is None or not tail_clauses:
        return fam, float(amount) * scale, is_abbr

    total_base = float(amount) * scale
    any_abbr = is_abbr
    for clause in tail_clauses:
        parsed = _parse_compound_clause(clause)
        if not parsed:
            return None, float(amount), False
        c_amt, c_unit = parsed
        c_fam, c_scale, c_abbr = _get_single_unit_family(c_unit)
        if c_fam != fam:
            return None, float(amount), False
        total_base += c_amt * c_scale
        any_abbr = any_abbr or c_abbr
    return fam, total_base, any_abbr


def get_unit_family(unit_str: str) -> tuple[str | None, float, bool]:
    """
    Determine the measurement family and base unit scale factor for a unit string.

    Returns:
        tuple of (family_name, scale_to_base, is_abbreviation).
    """
    clean = (unit_str or "").strip()
    if not clean:
        return None, 1.0, False
    if _COMPOUND_TAIL_RE.match(clean):
        return to_base_quantity(1, clean)
    return _get_single_unit_family(clean)


def can_combine_units(unit1: str, unit2: str) -> bool:
    """
    Determine whether two measurement units are compatible and can be combined.

    Units can combine if they are identical (singularized), or if both belong to the same
    convertible measurement system (e.g. pints and quarts, ounces and pounds, compound volume).
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


def _unit_label(qty: float, abbr: str, singular: str, plural: str, use_abbr: bool) -> str:
    """Select abbreviated or singular/plural full unit label for a numeric quantity."""
    if use_abbr:
        return abbr
    return singular if round(qty, 2) == 1.0 else plural


def _format_compound_parts(parts: list[tuple[Decimal, str]]) -> tuple[Decimal, str]:
    """
    Format decomposed [(qty, unit_label), ...] into a ShoppingListItem-compatible (amount, unit_str).
    Example: [(1, 'gallon'), (1, 'cup')] -> (Decimal('1.00'), 'gallon and 1 cup').
    """
    head_amt, head_unit = parts[0]
    head_dec = Decimal(str(head_amt)).quantize(Decimal("0.01"))
    if len(parts) == 1:
        return head_dec, head_unit

    tail_strs = [f"{format_amount(amt)} {unit}".strip() for amt, unit in parts[1:]]
    if len(tail_strs) == 1:
        return head_dec, f"{head_unit} and {tail_strs[0]}"
    return head_dec, f"{head_unit}, " + " and ".join([", ".join(tail_strs[:-1]), tail_strs[-1]])


def _is_clean_multiple(ratio: float, allowed_fracs: tuple[float, ...], tol: float = 0.012) -> bool:
    """Return True if the fractional remainder of ratio matches an allowed culinary fraction."""
    frac = ratio - int(ratio)
    if frac < tol or abs(frac - 1.0) < tol:
        return True
    return any(abs(frac - target) <= tol for target in allowed_fracs)


def _decompose_volume_us_remainder(
    rem_tsp: float,
    prefer_abbr: bool,
    prefer_c_abbr: bool,
) -> list[tuple[Decimal, str]]:
    """Decompose remaining tsp under a larger US volume unit into readable whole/fractional parts."""
    parts: list[tuple[Decimal, str]] = []
    remaining = rem_tsp
    steps = (
        ("qt", "quart", "quarts", 192.0, prefer_abbr),
        ("pt", "pint", "pints", 96.0, prefer_abbr),
        ("c", "cup", "cups", 48.0, prefer_c_abbr),
        ("tbsp", "tablespoon", "tablespoons", 3.0, prefer_abbr),
    )
    for abbr, sing, plur, factor, use_abbr in steps:
        if len(parts) >= 2:
            break
        if remaining + 0.2 < factor:
            continue
        if abs(remaining - factor) < 0.25:
            whole = 1
        else:
            whole = int((remaining + 0.05) // factor)
        if whole >= 1:
            parts.append((Decimal(str(whole)), _unit_label(float(whole), abbr, sing, plur, use_abbr)))
            remaining = max(0.0, remaining - whole * factor)
            if remaining < 0.25:
                return parts

    if remaining >= 0.25:
        # Clean sub-cup fraction like 1/2, 1/3, 2/3, 1/4, 3/4 cup instead of messy tbsp/tsp
        if 12.0 <= remaining < 48.0 and _is_clean_multiple(remaining / 48.0, (0.25, 1.0 / 3.0, 0.5, 2.0 / 3.0, 0.75)):
            cup_val = round(remaining / 48.0, 2)
            parts.append((Decimal(str(cup_val)), _unit_label(1.0, "c", "cup", "cups", prefer_c_abbr)))
        else:
            tsp_val = round(remaining, 2)
            if abs(tsp_val - round(tsp_val)) < 0.1 and tsp_val >= 1.0:
                tsp_val = float(round(tsp_val))
            parts.append((Decimal(str(tsp_val)), _unit_label(tsp_val, "tsp", "teaspoon", "teaspoons", prefer_abbr)))
    return parts


def _format_volume_us(
    total_tsp: float,
    prefer_abbr: bool,
    prefer_c_abbr: bool,
) -> tuple[Decimal, str]:
    """Format US volume base total (in tsp) into standard or compound units."""
    if total_tsp >= 12.0 and abs(total_tsp - round(total_tsp)) <= 0.22:
        total_tsp = float(round(total_tsp))

    # Gallons (1 gallon = 768 tsp = 16 cups)
    if total_tsp >= 768.0 or abs(total_tsp - 768.0) < 0.25:
        whole_gal = int((total_tsp + 0.25) // 768.0)
        rem_tsp = max(0.0, total_tsp - whole_gal * 768.0)
        if rem_tsp < 0.25:
            return Decimal(str(whole_gal)).quantize(Decimal("0.01")), _unit_label(
                float(whole_gal), "gal", "gallon", "gallons", prefer_abbr
            )
        if abs(rem_tsp - 384.0) < 0.25:
            half_gal = whole_gal + 0.5
            return Decimal(str(half_gal)).quantize(Decimal("0.01")), _unit_label(
                half_gal, "gal", "gallon", "gallons", prefer_abbr
            )
        head = (Decimal(str(whole_gal)), _unit_label(float(whole_gal), "gal", "gallon", "gallons", prefer_abbr))
        rem_parts = _decompose_volume_us_remainder(rem_tsp, prefer_abbr, prefer_c_abbr)
        return _format_compound_parts([head, *rem_parts[:2]])

    # Quarts (1 quart = 192 tsp = 2 pints)
    if total_tsp >= 192.0:
        quarts = round(total_tsp / 192.0, 2)
        if _is_clean_multiple(total_tsp / 192.0, (0.5,)):
            return Decimal(str(quarts)).quantize(Decimal("0.01")), _unit_label(
                quarts, "qt", "quart", "quarts", prefer_abbr
            )
        whole_qt = int((total_tsp + 0.2) // 192.0)
        rem_tsp = max(0.0, total_tsp - whole_qt * 192.0)
        head = (Decimal(str(whole_qt)), _unit_label(float(whole_qt), "qt", "quart", "quarts", prefer_abbr))
        rem_parts = _decompose_volume_us_remainder(rem_tsp, prefer_abbr, prefer_c_abbr)
        return _format_compound_parts([head, *rem_parts[:2]])

    # Pints (1 pint = 96 tsp = 2 cups)
    if total_tsp >= 96.0:
        pints = round(total_tsp / 96.0, 2)
        if _is_clean_multiple(total_tsp / 96.0, (0.5,)):
            return Decimal(str(pints)).quantize(Decimal("0.01")), _unit_label(
                pints, "pt", "pint", "pints", prefer_abbr
            )
        whole_pt = int((total_tsp + 0.2) // 96.0)
        rem_tsp = max(0.0, total_tsp - whole_pt * 96.0)
        head = (Decimal(str(whole_pt)), _unit_label(float(whole_pt), "pt", "pint", "pints", prefer_abbr))
        rem_parts = _decompose_volume_us_remainder(rem_tsp, prefer_abbr, prefer_c_abbr)
        return _format_compound_parts([head, *rem_parts[:2]])

    # Cups (1 cup = 48 tsp)
    if total_tsp >= 16.0:
        cups = round(total_tsp / 48.0, 2)
        if _is_clean_multiple(total_tsp / 48.0, (0.25, 1.0 / 3.0, 0.5, 2.0 / 3.0, 0.75)):
            return Decimal(str(cups)).quantize(Decimal("0.01")), _unit_label(
                cups, "c", "cup", "cups", prefer_c_abbr
            )
        if total_tsp >= 48.0:
            whole_cups = int((total_tsp + 0.2) // 48.0)
            rem_tsp = max(0.0, total_tsp - whole_cups * 48.0)
            head = (Decimal(str(whole_cups)), _unit_label(float(whole_cups), "c", "cup", "cups", prefer_c_abbr))
            rem_parts = _decompose_volume_us_remainder(rem_tsp, prefer_abbr, prefer_c_abbr)
            return _format_compound_parts([head, *rem_parts[:2]])
        return Decimal(str(cups)).quantize(Decimal("0.01")), _unit_label(
            cups, "c", "cup", "cups", prefer_c_abbr
        )

    # Tablespoons (1 tbsp = 3 tsp)
    if total_tsp >= 3.0:
        if abs(total_tsp % 3.0) < 0.05 or abs((total_tsp % 3.0) - 3.0) < 0.05:
            tbsp = round(total_tsp / 3.0, 2)
            return Decimal(str(tbsp)).quantize(Decimal("0.01")), _unit_label(
                tbsp, "tbsp", "tablespoon", "tablespoons", prefer_abbr
            )
        whole_tbsp = int(total_tsp // 3.0)
        rem_tsp = round(total_tsp - whole_tbsp * 3.0, 2)
        if whole_tbsp >= 1 and rem_tsp >= 0.25:
            head = (Decimal(str(whole_tbsp)), _unit_label(float(whole_tbsp), "tbsp", "tablespoon", "tablespoons", prefer_abbr))
            rem_unit = _unit_label(rem_tsp, "tsp", "teaspoon", "teaspoons", prefer_abbr)
            return _format_compound_parts([head, (Decimal(str(rem_tsp)), rem_unit)])

    tsp_val = round(total_tsp, 2)
    return Decimal(str(tsp_val)).quantize(Decimal("0.01")), _unit_label(
        tsp_val, "tsp", "teaspoon", "teaspoons", prefer_abbr
    )


def _format_weight_us(total_oz: float, prefer_abbr: bool) -> tuple[Decimal, str]:
    """Format US weight (oz, lb) cleanly, using compound 'lb and oz' when non-quarterly."""
    if total_oz >= 16.0:
        lbs = round(total_oz / 16.0, 2)
        if _is_clean_multiple(total_oz / 16.0, (0.25, 0.5, 0.75)):
            return Decimal(str(lbs)).quantize(Decimal("0.01")), _unit_label(
                lbs, "lb", "pound", "pounds", prefer_abbr
            )
        whole_lb = int(total_oz // 16.0)
        rem_oz = round(total_oz - whole_lb * 16.0, 2)
        head = (Decimal(str(whole_lb)), _unit_label(float(whole_lb), "lb", "pound", "pounds", prefer_abbr))
        rem_unit = _unit_label(rem_oz, "oz", "ounce", "ounces", prefer_abbr)
        return _format_compound_parts([head, (Decimal(str(rem_oz)), rem_unit)])

    oz_val = round(total_oz, 2)
    return Decimal(str(oz_val)).quantize(Decimal("0.01")), _unit_label(
        oz_val, "oz", "ounce", "ounces", prefer_abbr
    )


def _format_metric(
    total_base: float,
    prefer_abbr: bool,
    small_abbr: str,
    small_sing: str,
    small_plur: str,
    big_abbr: str,
    big_sing: str,
    big_plur: str,
) -> tuple[Decimal, str]:
    """Format metric weight/volume (g/kg or ml/l) without losing sub-10g/ml precision."""
    if total_base >= 1000.0:
        big_rounded = round(total_base / 1000.0, 2)
        if abs(big_rounded * 1000.0 - total_base) < 0.5:
            return Decimal(str(big_rounded)).quantize(Decimal("0.01")), _unit_label(
                big_rounded, big_abbr, big_sing, big_plur, prefer_abbr
            )
        whole_big = int(total_base // 1000.0)
        rem_small = round(total_base - whole_big * 1000.0, 2)
        head = (Decimal(str(whole_big)), _unit_label(float(whole_big), big_abbr, big_sing, big_plur, prefer_abbr))
        rem_unit = _unit_label(rem_small, small_abbr, small_sing, small_plur, prefer_abbr)
        return _format_compound_parts([head, (Decimal(str(rem_small)), rem_unit)])

    small_val = round(total_base, 2)
    return Decimal(str(small_val)).quantize(Decimal("0.01")), _unit_label(
        small_val, small_abbr, small_sing, small_plur, prefer_abbr
    )


def combine_amounts_and_units(
    amount1: Decimal | float | int,
    unit1: str,
    amount2: Decimal | float | int,
    unit2: str,
) -> tuple[Decimal, str]:
    """
    Combine two quantities and their measurement units, converting up to natural units
    and expressing mixed US totals clearly (e.g. '10 cups + 7 cups' -> '1 gallon and 1 cup').
    """
    amt1 = float(amount1)
    amt2 = float(amount2)
    u1_clean = unit1.strip()
    u2_clean = unit2.strip()

    # Both empty units (pure counts, e.g. 2 bananas + 3 bananas = 5 bananas)
    if not u1_clean and not u2_clean:
        return Decimal(str(amt1 + amt2)).quantize(Decimal("0.01")), ""

    fam1, total1, is_abbr1 = to_base_quantity(amt1, u1_clean)
    fam2, total2, is_abbr2 = to_base_quantity(amt2, u2_clean)
    prefer_abbr = is_abbr1 and is_abbr2 if (fam1 == "volume_us" and is_abbr1 != is_abbr2) else (is_abbr1 or is_abbr2)
    prefer_c_abbr = u1_clean.lower() == "c" and u2_clean.lower() == "c"

    if fam1 == "volume_us" and fam2 == "volume_us":
        return _format_volume_us(total1 + total2, prefer_abbr, prefer_c_abbr)

    if fam1 == "weight_us" and fam2 == "weight_us":
        return _format_weight_us(total1 + total2, is_abbr1 or is_abbr2)

    if fam1 == "weight_metric" and fam2 == "weight_metric":
        return _format_metric(total1 + total2, is_abbr1 or is_abbr2, "g", "gram", "grams", "kg", "kilogram", "kilograms")

    if fam1 == "volume_metric" and fam2 == "volume_metric":
        return _format_metric(total1 + total2, is_abbr1 or is_abbr2, "ml", "milliliter", "milliliters", "l", "liter", "liters")

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

    fam1, val1, _ = to_base_quantity(amount1, u1_clean)
    fam2, val2, _ = to_base_quantity(amount2, u2_clean)

    if fam1 is not None and fam1 == fam2:
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

