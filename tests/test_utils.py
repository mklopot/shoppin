"""
Unit tests for string parsing, fractional numbers, culinary pluralization/singularization,
and unit conversions.
"""

from decimal import Decimal

from apps.core.utils import (
    combine_amounts_and_units,
    format_amount,
    parse_amount_and_unit,
    pluralize,
    pluralize_unit,
    singularize,
    singularize_unit,
)


def test_parse_amount_integer():
    amt, unit = parse_amount_and_unit("2")
    assert amt == Decimal("2.00")
    assert unit == ""


def test_parse_amount_with_unit():
    amt, unit = parse_amount_and_unit("1 lb")
    assert amt == Decimal("1.00")
    assert unit == "lb"


def test_parse_amount_fraction():
    amt, unit = parse_amount_and_unit("1/2 tsp")
    assert amt == Decimal("0.50")
    assert unit == "tsp"


def test_parse_amount_fraction_in_unit():
    amt, unit = parse_amount_and_unit("1/3 cups")
    assert amt == Decimal("0.33")
    assert unit == "cups"


def test_parse_amount_word_numbers():
    amt1, unit1 = parse_amount_and_unit("one pint")
    assert amt1 == Decimal("1.00")
    assert unit1 == "pint"

    amt2, unit2 = parse_amount_and_unit("two quarts")
    assert amt2 == Decimal("2.00")
    assert unit2 == "quarts"

    amt3, unit3 = parse_amount_and_unit("half cup")
    assert amt3 == Decimal("0.50")
    assert unit3 == "cup"


def test_parse_amount_mixed_fraction():
    amt, unit = parse_amount_and_unit("1 1/2 cups")
    assert amt == Decimal("1.50")
    assert unit == "cups"


def test_parse_amount_decimal():
    amt, unit = parse_amount_and_unit("0.25 kg")
    assert amt == Decimal("0.25")
    assert unit == "kg"


def test_singularize_culinary_exceptions():
    # Irregular items that inflection corrupts
    assert singularize("cloves") == "clove"
    assert singularize("slices") == "slice"
    assert singularize("slice") == "slice"
    assert singularize("loaves") == "loaf"
    assert singularize("leaves") == "leaf"
    assert singularize("halves") == "half"
    assert singularize("chilies") == "chili"
    assert singularize("chilis") == "chili"
    assert singularize("radishes") == "radish"
    assert singularize("squashes") == "squash"
    assert singularize("tomatoes") == "tomato"
    assert singularize("potatoes") == "potato"
    assert singularize("cherries") == "cherry"
    assert singularize("berries") == "berry"
    assert singularize("bunches") == "bunch"
    assert singularize("heads") == "head"

    # Mass / uncountable food nouns
    assert singularize("asparagus") == "asparagus"
    assert singularize("molasses") == "molasses"
    assert singularize("hummus") == "hummus"
    assert singularize("couscous") == "couscous"
    assert singularize("citrus") == "citrus"
    assert singularize("pasta") == "pasta"
    assert singularize("rice") == "rice"
    assert singularize("corn") == "corn"
    assert singularize("broccoli") == "broccoli"
    assert singularize("celery") == "celery"

    # 'X of Y' phrases
    assert singularize("cloves of garlic") == "clove of garlic"
    assert singularize("heads of lettuce") == "head of lettuce"
    assert singularize("slices of bread") == "slice of bread"


def test_pluralize_culinary_exceptions():
    assert pluralize("clove") == "cloves"
    assert pluralize("slice") == "slices"
    assert pluralize("loaf") == "loaves"
    assert pluralize("leaf") == "leaves"
    assert pluralize("half") == "halves"
    assert pluralize("chili") == "chilies"
    assert pluralize("radish") == "radishes"
    assert pluralize("squash") == "squashes"
    assert pluralize("potato") == "potatoes"
    assert pluralize("tomato") == "tomatoes"
    assert pluralize("cherry") == "cherries"
    assert pluralize("bunch") == "bunches"
    assert pluralize("head") == "heads"

    # Mass / uncountable food nouns
    assert pluralize("asparagus") == "asparagus"
    assert pluralize("molasses") == "molasses"
    assert pluralize("hummus") == "hummus"
    assert pluralize("couscous") == "couscous"
    assert pluralize("pasta") == "pasta"
    assert pluralize("rice") == "rice"

    # Invariant unit abbreviations
    assert pluralize("lb") == "lb"
    assert pluralize("oz") == "oz"
    assert pluralize("tsp") == "tsp"
    assert pluralize("tbsp") == "tbsp"
    assert pluralize("pt") == "pt"
    assert pluralize("qt") == "qt"
    assert pluralize("gal") == "gal"

    # 'X of Y' phrases
    assert pluralize("clove of garlic") == "cloves of garlic"
    assert pluralize("head of lettuce") == "heads of lettuce"


def test_fractions_in_units():
    assert singularize_unit("1/3 cups") == "1/3 cup"
    assert pluralize_unit("1/3 cup") == "1/3 cups"
    assert singularize_unit("1/2 slices") == "1/2 slice"
    assert pluralize_unit("1/2 slice") == "1/2 slices"
    assert singularize_unit("1/4 tsp") == "1/4 tsp"
    assert pluralize_unit("1/4 tsp") == "1/4 tsp"


def test_one_pint_plus_one_pint_makes_a_quart():
    # 1 pint + 1 pint = 1 quart
    amt, unit = combine_amounts_and_units(1, "pint", 1, "pint")
    assert amt == Decimal("1.00")
    assert unit == "quart"

    # Abbreviation: 1 pt + 1 pt = 1 qt
    amt_abbr, unit_abbr = combine_amounts_and_units(1, "pt", 1, "pt")
    assert amt_abbr == Decimal("1.00")
    assert unit_abbr == "qt"


def test_volume_unit_conversions():
    # 1 quart + 1 pint = 1.5 quarts
    amt1, unit1 = combine_amounts_and_units(1, "quart", 1, "pint")
    assert amt1 == Decimal("1.50")
    assert unit1 == "quarts"

    # 2 quarts + 2 quarts = 1 gallon
    amt2, unit2 = combine_amounts_and_units(2, "quarts", 2, "quarts")
    assert amt2 == Decimal("1.00")
    assert unit2 == "gallon"

    # 1 cup + 1 cup = 1 pint
    amt3, unit3 = combine_amounts_and_units(1, "cup", 1, "cup")
    assert amt3 == Decimal("1.00")
    assert unit3 == "pint"

    # 2 cups + 2 cups = 1 quart
    amt4, unit4 = combine_amounts_and_units(2, "cups", 2, "cups")
    assert amt4 == Decimal("1.00")
    assert unit4 == "quart"

    # Fractions: 1/3 cup + 1/3 cup = 2/3 cup
    amt5, unit5 = combine_amounts_and_units(1, "1/3 cup", 1, "1/3 cup")
    assert amt5 == Decimal("0.67")
    assert unit5 == "cups"

    # Fractions: 2/3 cup + 1/3 cup = 1 cup
    amt6, unit6 = combine_amounts_and_units(Decimal("0.67"), "cup", 1, "1/3 cup")
    assert amt6 == Decimal("1.00")
    assert unit6 == "cup"


def test_weight_and_metric_conversions():
    # 8 oz + 8 oz = 1 lb
    amt1, unit1 = combine_amounts_and_units(8, "oz", 8, "oz")
    assert amt1 == Decimal("1.00")
    assert unit1 == "lb"

    # 500 g + 500 g = 1 kg
    amt2, unit2 = combine_amounts_and_units(500, "g", 500, "g")
    assert amt2 == Decimal("1.00")
    assert unit2 == "kg"

    # 500 ml + 500 ml = 1 l
    amt3, unit3 = combine_amounts_and_units(500, "ml", 500, "ml")
    assert amt3 == Decimal("1.00")
    assert unit3 == "l"


def test_format_amount():
    assert format_amount(0.33) == "1/3"
    assert format_amount(0.5) == "1/2"
    assert format_amount(0.67) == "2/3"
    assert format_amount(0.25) == "1/4"
    assert format_amount(0.75) == "3/4"
    assert format_amount(1.5) == "1 1/2"
    assert format_amount(1.33) == "1 1/3"
    assert format_amount(2.0) == "2"


def test_categorizer_tally_occurrences():
    from apps.core.categorizer import categorizer
    assert categorizer.get_category("beans") == "canned vegetables"
    assert categorizer.get_category("black bean patty") == "frozen"
    assert categorizer.get_category("bell pepper") == "produce"
    assert categorizer.get_category("unknown_exotic_food_123") == "other"
