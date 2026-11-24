"""
Heuristic linting and database unit-consistency service for recipe ingredients.

Because recipe ingredients sync directly onto household Shopping Lists, this module
helps authors enter brief, store-buyable item names (e.g. 'onion' instead of
'chopped onion') and realistic, consistent amounts and units (e.g. '8 oz sour cream'
rather than '1 sour cream') matching existing database conventions.
"""

import re
import sys
import time
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from apps.core.categorizer import categorizer
from apps.core.units import (
    UNCOUNTABLE_FOODS,
    VOLUME_METRIC_IN_ML,
    VOLUME_UNITS_IN_TSP,
    WEIGHT_METRIC_IN_G,
    WEIGHT_US_IN_OZ,
    can_combine_units,
    format_amount,
    pluralize_unit,
    singularize,
)
from apps.core.utils import COMMON_UNITS, parse_amount_and_unit, parse_ingredient_line
from apps.recipes.models import Ingredient

_PROFILES_CACHE: dict[str, dict[str, Any]] | None = None
_PROFILES_CACHE_TIME: float = 0.0
_PROFILES_CACHE_TTL_SECONDS = 60.0

# Preparation/cooking verbs that do not belong on a shopping list item name
ALWAYS_PREP_WORDS: set[str] = {
    "chopped", "finely", "coarsely", "thinly", "roughly", "freshly", "minced",
    "melted", "softened", "beaten", "whisked", "scrambled", "peeled", "deveined",
    "seeded", "deseeded", "cored", "stemmed", "trimmed", "halved", "quartered",
    "crushed", "mashed", "pureed", "julienned", "cubed", "rinsed", "drained",
    "squeezed", "zested", "toasted", "browned", "cooked", "boiled", "steamed",
    "blanched", "thawed", "divided", "warmed", "chilled",
}

# Prep words that are valid only for certain pre-packaged/deli grocery items
CONTEXT_PREP_WORDS: set[str] = {
    "diced", "sliced", "grated", "shredded", "crumbled",
}

SIZE_MODIFIER_WORDS: set[str] = {
    "large", "medium", "med", "small", "extra-large", "jumbo",
}

# Foods legitimately sold pre-diced, pre-sliced, shredded, grated, or crumbled
PREPACKAGED_PREP_NOUNS: set[str] = {
    "tomato", "tomatoes", "cheese", "cheddar", "mozzarella", "parmesan",
    "swiss", "provolone", "feta", "gorgonzola", "monterey", "gruyere",
    "bread", "ham", "turkey", "bacon", "pepperoni", "salami", "bologna",
    "almond", "almonds", "coconut", "cabbage", "slaw", "coleslaw",
    "hashbrown", "hashbrowns", "pineapple", "peach", "peaches",
}

# Multi-word instructions/notes that belong in directions or the Optional checkbox
INSTRUCTION_PHRASES: tuple[tuple[str, str], ...] = (
    ("to taste", "Move 'to taste' to Directions or omit it from the shopping item name."),
    ("as needed", "Move 'as needed' to Directions."),
    ("for serving", "Move 'for serving' to Directions."),
    ("for garnish", "Move 'for garnish' to Directions."),
    ("for frying", "Move 'for frying' to Directions."),
    ("for greasing", "Move 'for greasing' to Directions."),
    ("at room temperature", "Move temperature notes like 'at room temperature' to Directions."),
    ("room temperature", "Move temperature notes like 'room temperature' to Directions."),
    ("divided", "Move 'divided' into Directions; the shopping list only needs total quantity."),
)

# Categories whose items almost always require an explicit weight/volume/package unit
UNIT_REQUIRED_CATEGORIES: set[str] = {
    "baking",
    "beverages",
    "cereal and breakfast",
    "condiments",
    "dairy",
    "drinks",
    "dry pasta and pasta sauce",
    "eggs and dairy",
    "juices",
    "nut butters and jams",
    "oil",
    "rice beans and grains",
    "salad dressing",
    "seasoning mix",
    "soup",
    "spices",
    "tea and coffee",
    "wine and beer",
}

# Explicit discrete/packaged nouns where a bare count ("1 ...", "2 ...") makes sense
COUNTABLE_ITEM_KEYWORDS: set[str] = {
    "egg", "eggs", "onion", "onions", "shallot", "shallots", "scallion", "scallions",
    "avocado", "avocados", "tomato", "tomatoes", "potato", "potatoes", "yam", "yams",
    "carrot", "carrots", "cucumber", "cucumbers", "zucchini", "zucchinis", "squash",
    "lemon", "lemons", "lime", "limes", "orange", "oranges", "apple", "apples",
    "banana", "bananas", "pear", "pears", "peach", "peaches", "plum", "plums",
    "mango", "mangoes", "pepper", "peppers", "jalapeno", "jalapenos", "chili", "chilis",
    "chilies", "beet", "beets", "turnip", "turnips", "radish", "radishes",
    "bagel", "bagels", "bun", "buns", "roll", "rolls", "tortilla", "tortillas",
    "pita", "croissant", "english muffin", "loaf", "baguette",
    "breast", "breasts", "thigh", "thighs", "drumstick", "wing", "wings",
    "chop", "chops", "steak", "steaks", "cutlet", "cutlets", "fillet", "fillets",
    "patty", "patties", "sausage", "hot dog", "hot dogs", "link", "links",
    "can", "jar", "bottle", "package", "packet", "pouch", "bag", "box", "block",
    "carton", "tub", "stick", "head", "bunch", "clove", "bulb", "sheet", "sheets",
    "crust", "cracker", "crackers", "cookie", "cookies",
}

BULK_LIQUID_OR_POWDER_KEYWORDS: set[str] = {
    "cream", "yogurt", "milk", "butter", "margarine", "cheese", "broth", "stock",
    "sauce", "paste", "puree", "oil", "vinegar", "juice", "wine", "water", "beer",
    "flour", "sugar", "salt", "pepper", "seasoning", "spice", "powder", "extract",
    "honey", "syrup", "molasses", "mustard", "ketchup", "mayo", "mayonnaise",
    "salsa", "hummus", "tahini", "dressing", "dip", "rice", "quinoa", "oats",
    "oatmeal", "couscous", "cereal", "coffee", "tea", "cocoa", "chocolate chips",
}

COUNTABLE_WHOLE_PREFIXES: tuple[str, ...] = ("whole ", "rotisserie ")

SMALL_SPICE_UNITS: set[str] = {"tsp", "teaspoon", "teaspoons", "t", "pinch", "pinches", "dash", "dashes"}
LARGE_VOLUME_OR_WEIGHT_UNITS: set[str] = {
    "lb", "lbs", "pound", "pounds", "kg", "kilogram", "kilograms",
    "gal", "gallon", "gallons", "qt", "quart", "quarts", "head", "heads", "loaf", "loaves",
}
PROTEIN_KEYWORDS: set[str] = {
    "beef", "pork", "chicken", "turkey", "lamb", "steak", "fish",
    "salmon", "tuna", "shrimp", "bacon", "ham", "sausage", "tofu",
}
SPICE_OR_SEASONING_KEYWORDS: set[str] = {
    "salt", "cinnamon", "cumin", "paprika", "oregano", "thyme", "rosemary",
    "nutmeg", "turmeric", "chili powder", "garlic powder", "onion powder",
    "cayenne", "baking powder", "baking soda", "vanilla", "yeast",
}

CONTAINERS_DEFAULT_8OZ: set[str] = {
    "sour cream", "cream cheese", "tomato paste", "tomato sauce", "yogurt",
    "greek yogurt", "ricotta", "cottage cheese", "mascarpone", "heavy cream",
    "whipping cream", "half and half", "half-and-half", "hummus", "pesto", "salsa",
    "cheddar cheese", "mozzarella", "feta",
}


def _normalize_ingredient_key(name: str) -> str:
    """Return normalized singularized lookup key for database consistency matching."""
    cleaned = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not cleaned:
        return ""
    return singularize(cleaned).lower()


def _is_valid_db_unit(unit: str) -> bool:
    """Filter out malformed legacy unit artifacts such as leading '/2 cup'."""
    u = (unit or "").strip()
    if not u:
        return True
    return not (u.startswith("/") or not any(ch.isalpha() for ch in u))


def _suggest_amount_for_unit(
    unit: str,
    unit_amounts: list[Decimal],
    name_lower: str,
    user_amount: Decimal | None = None,
) -> str:
    """Choose a sensible formatted '<amount> <unit>' suggestion."""
    if not unit:
        amt = user_amount if (user_amount and user_amount > 0) else Decimal("1")
        return format_amount(amt)

    is_oz = singularize(unit.lower()) in ("oz", "ounce")
    is_retail_oz = any(k in name_lower for k in CONTAINERS_DEFAULT_8OZ)
    if is_retail_oz and is_oz and (
        not unit_amounts
        or Decimal("8.00") in unit_amounts
        or (user_amount is not None and user_amount <= Decimal("1.00"))
    ):
        return f"8 {unit}"

    if unit_amounts:
        common_amt = Counter(unit_amounts).most_common(1)[0][0]
        if user_amount and user_amount > Decimal("1.00"):
            common_amt = user_amount
        disp_unit = pluralize_unit(unit) if common_amt > Decimal("1.00") else unit
        return f"{format_amount(common_amt)} {disp_unit}"

    if user_amount and user_amount > Decimal("0.00"):
        return f"{format_amount(user_amount)} {unit}"
    return f"1 {unit}"


def get_ingredient_unit_profiles(*, use_cache: bool = True) -> dict[str, dict[str, Any]]:
    """
    Aggregate historical unit and amount conventions per normalized ingredient
    across all recipes currently stored in the database.
    """
    global _PROFILES_CACHE, _PROFILES_CACHE_TIME
    bypass_cache = (not use_cache) or ("pytest" in sys.modules)
    now = time.time()
    if not bypass_cache and _PROFILES_CACHE is not None and (now - _PROFILES_CACHE_TIME) < _PROFILES_CACHE_TTL_SECONDS:
        return _PROFILES_CACHE

    unit_tallies: dict[str, Counter[str]] = defaultdict(Counter)
    unit_amounts: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(list))
    display_names: dict[str, Counter[str]] = defaultdict(Counter)

    for raw_name, raw_amt, raw_unit in Ingredient.objects.values_list("name", "amount", "amount_unit"):
        name_str = (raw_name or "").strip()
        if not name_str:
            continue
        key = _normalize_ingredient_key(name_str)
        if not key:
            continue
        raw_u = (raw_unit or "").strip().lower()
        if not _is_valid_db_unit(raw_u):
            continue
        unit_str = _canonical_db_unit(raw_u)

        display_names[key][name_str] += 1
        unit_tallies[key][unit_str] += 1
        if raw_amt is not None and raw_amt > 0:
            unit_amounts[key][unit_str].append(raw_amt)

    profiles: dict[str, dict[str, Any]] = {}
    for key, tally in unit_tallies.items():
        total = sum(tally.values())
        unitless_count = tally.get("", 0)
        measured_counts = [(u, c) for u, c in tally.most_common() if u]
        measured_total = sum(c for _, c in measured_counts)

        unit_entries = [
            {
                "unit": u,
                "count": c,
                "example": _suggest_amount_for_unit(
                    u, unit_amounts[key][u], key, user_amount=Decimal("1.00")
                ),
                "amounts": unit_amounts[key][u],
            }
            for u, c in measured_counts[:4]
        ]

        profiles[key] = {
            "key": key,
            "canonical_name": display_names[key].most_common(1)[0][0],
            "total_count": total,
            "unitless_count": unitless_count,
            "measured_count": measured_total,
            "mostly_measured": measured_total > unitless_count,
            "mostly_unitless": unitless_count > measured_total,
            "preferred_unit": measured_counts[0][0] if measured_counts else "",
            "unit_entries": unit_entries,
        }

    if not bypass_cache:
        _PROFILES_CACHE = profiles
        _PROFILES_CACHE_TIME = now
    return profiles


def _strip_parentheticals(
    working: str,
    prep_notes: list[str],
    warnings: list[dict[str, Any]],
) -> str:
    """Detect and strip parenthetical preparation or optional notes from ingredient names."""
    parens = re.findall(r"\(([^()]+)\)", working)
    if not parens:
        return working
    stripped = re.sub(r"\s*\([^()]*\)", "", working).strip(" ,;-")
    if not stripped:
        return working

    paren_joined = ", ".join(p.strip() for p in parens if p.strip())
    if "optional" in paren_joined.lower():
        warnings.append({
            "code": "optional_in_name",
            "severity": "warning",
            "message": "Use the Optional checkbox instead of writing '(optional)' in the ingredient name.",
            "suggested_name": stripped,
        })
    else:
        prep_notes.append(paren_joined)
        warnings.append({
            "code": "prep_in_name",
            "severity": "warning",
            "message": f"Move parenthetical note '({paren_joined})' to Directions so the shopping list item stays clean.",
            "suggested_name": stripped,
        })
    return stripped


def _strip_instruction_phrases(
    working: str,
    prep_notes: list[str],
    warnings: list[dict[str, Any]],
) -> str:
    """Detect serving instructions or 'optional' keywords inside ingredient names."""
    for phrase, hint_msg in INSTRUCTION_PHRASES:
        pattern = re.compile(rf"[,;\s]*\b{re.escape(phrase)}\b[,;\s]*", re.IGNORECASE)
        if pattern.search(working):
            candidate = re.sub(r"\s+", " ", pattern.sub(" ", working).strip(" ,;-"))
            if candidate and candidate.lower() != working.lower():
                prep_notes.append(phrase)
                warnings.append({
                    "code": "instruction_in_name",
                    "severity": "warning",
                    "message": hint_msg,
                    "suggested_name": candidate,
                })
                working = candidate

    if re.search(r"\boptional\b", working, re.IGNORECASE):
        candidate = re.sub(r"[,;\s]*\boptional\b[,;\s]*", " ", working, flags=re.IGNORECASE).strip(" ,;-")
        if candidate:
            warnings.append({
                "code": "optional_in_name",
                "severity": "warning",
                "message": "Use the Optional checkbox instead of writing 'optional' in the ingredient name.",
                "suggested_name": candidate,
            })
            working = candidate
    return working


def _strip_prep_modifiers(
    working: str,
    prep_notes: list[str],
    warnings: list[dict[str, Any]],
) -> str:
    """Detect trailing comma prep or inline prep adjectives like 'chopped onion'."""
    if "," in working:
        head, tail = [part.strip() for part in working.split(",", 1)]
        tail_tokens = set(re.findall(r"[a-zA-Z-]+", tail.lower()))
        if head and tail and (tail_tokens & (ALWAYS_PREP_WORDS | CONTEXT_PREP_WORDS | SIZE_MODIFIER_WORDS)):
            prep_notes.append(tail)
            warnings.append({
                "code": "prep_word",
                "severity": "warning",
                "message": (
                    f"Enter '{head}' instead of '{working}' and mention '{tail}' in Directions — "
                    "stores do not sell ingredients pre-prepared that way."
                ),
                "suggested_name": head,
            })
            working = head

    tokens = re.findall(r"[a-zA-Z0-9'-]+", working)
    token_lowers = [t.lower() for t in tokens]
    found_always = [t for t in token_lowers if t in ALWAYS_PREP_WORDS]
    is_prepackaged_cut = any(n in token_lowers for n in PREPACKAGED_PREP_NOUNS)
    found_context = [t for t in token_lowers if t in CONTEXT_PREP_WORDS and not is_prepackaged_cut]
    prep_hits = found_always + found_context

    if prep_hits:
        removable = set(prep_hits) | SIZE_MODIFIER_WORDS
        kept = [t for t in tokens if t.lower() not in removable]
        if kept:
            suggested = re.sub(r"^(and|or)\s+", "", " ".join(kept), flags=re.IGNORECASE).strip()
            if suggested and suggested.lower() != working.lower():
                prep_desc = ", ".join(dict.fromkeys(prep_hits))
                prep_notes.append(prep_desc)
                warnings.append({
                    "code": "prep_word",
                    "severity": "warning",
                    "message": (
                        f"'{working}' includes preparation ('{prep_desc}'). Enter '{suggested}' here "
                        "and put preparation steps in Step-by-Step Directions."
                    ),
                    "suggested_name": suggested,
                })
                return suggested
    return working


def _check_embedded_quantity(working: str, warnings: list[dict[str, Any]]) -> str:
    """Warn if quantities or units were typed into the Ingredient Name field."""
    low = working.lower()
    if not working or low.startswith(("half and half", "half-and-half")):
        return working
    has_prefix = bool(re.match(r"^\s*\d", working)) or low.startswith(
        ("half ", "quarter ", "one ", "two ", "three ", "a ", "an ")
    )
    if not has_prefix:
        return working

    parsed_name, parsed_amt, parsed_unit = parse_ingredient_line(working)
    if (parsed_unit or re.match(r"^\s*\d", working)) and parsed_name and parsed_name.lower() != low:
        suggested_amt = f"{format_amount(parsed_amt)} {parsed_unit}".strip()
        warnings.append({
            "code": "embedded_quantity",
            "severity": "warning",
            "message": (
                f"Put quantities and units in Amount & Unit: enter '{parsed_name}' here "
                f"and '{suggested_amt}' in Amount & Unit."
            ),
            "suggested_name": parsed_name,
            "suggested_amount": suggested_amt,
        })
        return parsed_name
    return working


def _check_brevity(working: str, warnings: list[dict[str, Any]]) -> None:
    """Flag overly long ingredient names, alternatives, or comma-heavy phrasing."""
    words = [w for w in re.split(r"\s+", working) if w]
    if re.search(r"\s+or\s+|/", working, re.IGNORECASE):
        first_choice = re.split(r"\s+or\s+|/", working, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        warnings.append({
            "code": "brevity",
            "severity": "warning",
            "message": (
                f"Avoid alternatives in '{working}'. Pick one item for the Shopping List "
                f"(e.g. '{first_choice}') and note substitutes in Directions."
            ),
            "suggested_name": first_choice or None,
        })
    elif "," in working or len(words) >= 4 or len(working) > 40:
        warnings.append({
            "code": "brevity",
            "severity": "warning",
            "message": (
                f"Ingredient name '{working}' is long ({len(words)} words). Keep names brief "
                "(1-3 words as sold in stores) and move details to Directions."
            ),
        })


def _extract_suggested_clean_name(raw_name: str) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    """Run all ingredient name formatting heuristics and return clean suggestion, notes, and warnings."""
    warnings: list[dict[str, Any]] = []
    prep_notes: list[str] = []
    name = re.sub(r"\s+", " ", (raw_name or "").strip())
    if not name:
        return None, prep_notes, warnings

    working = _strip_parentheticals(name, prep_notes, warnings)
    working = _strip_instruction_phrases(working, prep_notes, warnings)
    working = _strip_prep_modifiers(working, prep_notes, warnings)
    working = _check_embedded_quantity(working, warnings)
    _check_brevity(working, warnings)

    cleaned_result = working if working.lower() != name.lower() else None
    return cleaned_result, prep_notes, warnings


def _infer_sensible_units_for_item(name: str, category: str) -> list[str]:
    """Infer sensible default '<amount> <unit>' suggestions based on food type and category."""
    low = (name or "").lower().strip()
    cat = (category or "").lower().strip()

    if any(k in low for k in CONTAINERS_DEFAULT_8OZ):
        return ["8 oz", "1 cup", "1 tbsp"]
    if any(k in low for k in SPICE_OR_SEASONING_KEYWORDS) or cat in ("spices", "seasoning mix"):
        return ["1 tsp", "1 tbsp"]
    if any(k in low for k in ("olive oil", "vegetable oil", "canola oil", "sesame oil", "vinegar", "soy sauce", "oil")) or cat == "oil":
        return ["1 tbsp", "1 tsp", "1 cup"]
    if any(k in low for k in PROTEIN_KEYWORDS) or cat in ("meat", "fish", "deli meat"):
        return ["1 lb", "8 oz"]
    if any(k in low for k in ("broth", "stock", "milk", "water", "wine", "juice")) or cat in ("beverages", "drinks", "juices", "soup"):
        return ["1 cup", "8 oz", "1 tbsp"]
    if cat in ("baking", "rice beans and grains", "cereal and breakfast"):
        return ["1 cup", "8 oz", "1 tbsp"]
    if cat in ("condiments", "salad dressing", "nut butters and jams"):
        return ["1 tbsp", "8 oz", "1 cup"]
    return ["8 oz", "1 cup", "1 tbsp"]


def _requires_unit_by_nature(name: str) -> tuple[bool, str]:
    """
    Determine whether an ingredient cannot sensibly appear unitless (e.g. '1 sour cream').
    Returns (requires_unit, inferred_category).
    """
    low = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not low:
        return False, "other"
    if low.startswith(COUNTABLE_WHOLE_PREFIXES):
        return False, categorizer.get_category(low)

    tokens = set(re.findall(r"[a-zA-Z]+", low))
    singular_tokens = {singularize(t).lower() for t in tokens}

    if (tokens | singular_tokens) & COUNTABLE_ITEM_KEYWORDS:
        bulk_suffixes = ("powder", "juice", "sauce", "paste", "oil", "vinegar", "noodles", "soup", "puree", "broth", "stock", "extract", "butter", "cream")
        if not any(kw in low for kw in bulk_suffixes):
            return False, categorizer.get_category(low)

    cat = categorizer.get_category(low).strip().lower()
    sing = singularize(low).lower()
    if sing in UNCOUNTABLE_FOODS or low in UNCOUNTABLE_FOODS:
        return True, cat
    if any(kw in low for kw in BULK_LIQUID_OR_POWDER_KEYWORDS):
        return True, cat
    if cat in UNIT_REQUIRED_CATEGORIES and not ((tokens | singular_tokens) & COUNTABLE_ITEM_KEYWORDS):
        return True, cat
    return False, cat


def _is_unit_absurd_for_item(name: str, unit: str) -> str | None:
    """Return warning message when a supplied unit makes no practical culinary sense."""
    low = (name or "").lower().strip()
    u_sing = singularize((unit or "").strip()).lower()
    if not low or not u_sing:
        return None

    tokens = set(re.findall(r"[a-zA-Z]+", low))
    singular_tokens = {singularize(t).lower() for t in tokens}

    if u_sing in SMALL_SPICE_UNITS and (singular_tokens & PROTEIN_KEYWORDS):
        if not any(kw in low for kw in ("bouillon", "base", "broth", "stock", "paste", "sauce", "fat", "dripping")):
            return f"'{unit}' is unusually small for '{name}'. Consider using 'lb' or 'oz'."

    if u_sing in LARGE_VOLUME_OR_WEIGHT_UNITS and any(k in low for k in SPICE_OR_SEASONING_KEYWORDS):
        return f"'{unit}' is unusually large for '{name}'. Usually measured in 'tsp' or 'tbsp'."

    if u_sing in SMALL_SPICE_UNITS and singular_tokens <= {"egg", "eggs", "large", "medium", "small"}:
        return f"'{unit}' does not make sense for '{name}'. Enter a whole egg count (e.g. '2')."

    return None


EXTRA_CULINARY_UNITS: set[str] = {
    "stick", "sticks", "dash", "dashes", "bulb", "bulbs", "ear", "ears",
    "sprig", "sprigs", "rib", "ribs", "stalk", "stalks", "sheet", "sheets",
    "block", "blocks", "carton", "cartons", "tub", "tubs", "box", "boxes",
    "pack", "packs", "packet", "packets", "pouch", "pouches", "drop", "drops",
}


UNIT_CANONICAL_ALIASES: dict[str, str] = {
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "ounce": "oz",
    "ounces": "oz",
    "pound": "lb",
    "pounds": "lb",
    "lbs": "lb",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "milliliter": "ml",
    "milliliters": "ml",
    "liter": "l",
    "liters": "l",
}


def _canonical_db_unit(unit: str) -> str:
    """Normalize a database unit string to canonical singular/abbreviated form."""
    clean = (unit or "").strip().lower()
    if not clean:
        return ""
    sing = singularize(clean).lower()
    return UNIT_CANONICAL_ALIASES.get(clean) or UNIT_CANONICAL_ALIASES.get(sing) or sing


def _is_known_unit_token(parsed_unit: str) -> bool:
    """Return True if parsed_unit matches a recognized culinary measurement unit."""
    if not parsed_unit:
        return False
    lower = parsed_unit.lower()
    u_tokens = lower.split()
    known = COMMON_UNITS | EXTRA_CULINARY_UNITS
    return (
        singularize(lower) in known
        or lower in known
        or lower in VOLUME_UNITS_IN_TSP
        or lower in WEIGHT_US_IN_OZ
        or lower in WEIGHT_METRIC_IN_G
        or lower in VOLUME_METRIC_IN_ML
        or any(tok in known for tok in u_tokens)
    )


def _are_units_consistent(unit_a: str, unit_b: str) -> bool:
    """Return True if unit_a matches unit_b directly or via a convertible measurement system."""
    if singularize((unit_a or "").strip().lower()) == singularize((unit_b or "").strip().lower()):
        return True
    return can_combine_units(unit_a, unit_b)


def lint_ingredient(
    name: str,
    raw_amount: str = "",
    profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Validate and generate shopping-list formatting warnings and unit consistency
    recommendations for a single recipe ingredient row.
    """
    raw_name = (name or "").strip()
    raw_amt_str = (raw_amount or "").strip()
    if not raw_name:
        return {
            "name": "",
            "cleaned_name": None,
            "parsed_amount": "",
            "parsed_unit": "",
            "warnings": [],
            "unit_hints": [],
            "db_usage_summary": "",
            "prep_notes": [],
        }

    if profiles is None:
        profiles = get_ingredient_unit_profiles()

    cleaned_name, prep_notes, name_warnings = _extract_suggested_clean_name(raw_name)
    eval_name = cleaned_name or raw_name
    eval_key = _normalize_ingredient_key(eval_name)

    parsed_amount, parsed_unit = parse_amount_and_unit(raw_amt_str or "1")
    if not raw_amt_str or raw_amt_str == "1":
        for w in name_warnings:
            if w.get("code") == "embedded_quantity" and w.get("suggested_amount"):
                parsed_amount, parsed_unit = parse_amount_and_unit(w["suggested_amount"])
                break

    warnings: list[dict[str, Any]] = list(name_warnings)
    unit_hints: list[str] = []
    db_usage_summary = ""

    if raw_amt_str and parsed_amount <= Decimal("0.00"):
        warnings.append({
            "code": "invalid_amount",
            "severity": "warning",
            "message": "Amount should be greater than 0.",
        })

    is_known_unit = _is_known_unit_token(parsed_unit)
    profile = profiles.get(eval_key) or profiles.get(_normalize_ingredient_key(raw_name))

    if profile and profile["unit_entries"] and not profile["mostly_unitless"]:
        top_units_desc = ", ".join(f"{e['unit']} ({e['count']}x)" for e in profile["unit_entries"][:3])
        db_usage_summary = f"Elsewhere in database for '{profile['canonical_name']}': {top_units_desc}"
        for entry in profile["unit_entries"][:3]:
            hint = entry["example"]
            if parsed_amount > Decimal("1.00") and not parsed_unit and singularize(entry["unit"]) not in ("oz", "ounce", "g", "ml"):
                hint = f"{format_amount(parsed_amount)} {entry['unit']}"
            if hint not in unit_hints:
                unit_hints.append(hint)

    requires_unit_nature, inferred_cat = _requires_unit_by_nature(eval_name)
    db_expects_unit = bool(profile and profile["mostly_measured"])

    if not parsed_unit and (db_expects_unit or requires_unit_nature):
        unit_hints = (unit_hints or _infer_sensible_units_for_item(eval_name, inferred_cat))[:3]
        example_display = unit_hints[0] if unit_hints else "8 oz"
        amt_label = format_amount(parsed_amount)
        if profile and profile["unit_entries"]:
            preferred_list = ", ".join(e["unit"] for e in profile["unit_entries"][:3])
            msg = (
                f"'{amt_label} {eval_name}' is missing a unit and is unclear on a shopping list — "
                f"try '{example_display} {eval_name}' (other recipes use: {preferred_list})."
            )
        else:
            msg = (
                f"'{amt_label} {eval_name}' is missing a unit — use a measurement unit such as "
                f"'{example_display} {eval_name}' so it makes sense on the shopping list."
            )
        warnings.append({
            "code": "missing_unit",
            "severity": "warning",
            "message": msg,
            "suggested_amount": example_display,
        })
    elif parsed_unit:
        absurd_msg = _is_unit_absurd_for_item(eval_name, parsed_unit)
        if absurd_msg:
            if not requires_unit_nature and not db_expects_unit:
                unit_hints = [format_amount(parsed_amount)]
            else:
                unit_hints = (unit_hints or _infer_sensible_units_for_item(eval_name, inferred_cat))[:3]
            warnings.append({
                "code": "unusual_unit",
                "severity": "warning",
                "message": absurd_msg,
                "suggested_amount": unit_hints[0] if unit_hints else None,
            })
        elif profile and profile["unit_entries"] and not profile["mostly_unitless"]:
            used_singulars = {singularize(e["unit"].lower()) for e in profile["unit_entries"]}
            preferred_unit = profile["preferred_unit"]
            matches_db = (
                singularize(parsed_unit.lower()) in used_singulars
                or any(_are_units_consistent(parsed_unit, e["unit"]) for e in profile["unit_entries"][:2])
            )
            if not matches_db and preferred_unit:
                suggested_amt = f"{format_amount(parsed_amount)} {preferred_unit}"
                if any(k in eval_key for k in CONTAINERS_DEFAULT_8OZ) and singularize(preferred_unit) in ("oz", "ounce") and parsed_amount == Decimal("1.00"):
                    suggested_amt = f"8 {preferred_unit}"
                if not is_known_unit:
                    suggested_amt = profile["unit_entries"][0]["example"]
                warnings.append({
                    "code": "inconsistent_unit",
                    "severity": "info",
                    "message": (
                        f"Other recipes use {', '.join(e['unit'] for e in profile['unit_entries'][:3])} "
                        f"for '{profile['canonical_name']}'. Using '{preferred_unit}' keeps shopping list "
                        "items consistent so quantities combine automatically."
                    ),
                    "suggested_amount": suggested_amt,
                })
        elif profile and profile["mostly_unitless"] and profile["unitless_count"] >= 2 and not is_known_unit:
            warnings.append({
                "code": "inconsistent_unit",
                "severity": "info",
                "message": (
                    f"Other recipes enter '{profile['canonical_name']}' as a count without a unit "
                    f"(e.g. '{format_amount(parsed_amount)}')."
                ),
                "suggested_amount": format_amount(parsed_amount),
            })

    return {
        "name": raw_name,
        "cleaned_name": cleaned_name,
        "parsed_amount": format_amount(parsed_amount),
        "parsed_unit": parsed_unit,
        "warnings": warnings,
        "unit_hints": unit_hints[:3],
        "db_usage_summary": db_usage_summary,
        "prep_notes": prep_notes,
    }


def lint_recipe_ingredients(
    names: list[str],
    amounts: list[str] | None = None,
) -> dict[str, Any]:
    """Lint an entire list of recipe ingredient rows using a shared DB profile snapshot."""
    profiles = get_ingredient_unit_profiles()
    amounts_list = amounts or []
    rows = []
    warning_count = 0
    for idx, raw_name in enumerate(names):
        raw_amt = amounts_list[idx] if idx < len(amounts_list) else ""
        res = lint_ingredient(raw_name, raw_amt, profiles=profiles)
        res["row_index"] = idx
        warning_count += sum(1 for w in res["warnings"] if w["severity"] == "warning")
        rows.append(res)
    return {
        "rows": rows,
        "warning_count": warning_count,
    }
