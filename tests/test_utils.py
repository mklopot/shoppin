from decimal import Decimal

from apps.core.utils import parse_amount_and_unit, pluralize, singularize


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


def test_parse_amount_mixed_fraction():
    amt, unit = parse_amount_and_unit("1 1/2 cups")
    assert amt == Decimal("1.50")
    assert unit == "cups"


def test_parse_amount_decimal():
    amt, unit = parse_amount_and_unit("0.25 kg")
    assert amt == Decimal("0.25")
    assert unit == "kg"


def test_singularize_and_pluralize():
    assert singularize("cloves") == "clove"
    assert singularize("apples") == "apple"
    assert pluralize("apple") == "apples"
    assert pluralize("lb") == "lb"


def test_categorizer_tally_occurrences():
    from apps.core.categorizer import categorizer
    # "beans" should be categorized based on biggest count ("canned vegetables") rather than first match ("frozen")
    assert categorizer.get_category("beans") == "canned vegetables"
    assert categorizer.get_category("black bean patty") == "frozen"
    assert categorizer.get_category("bell pepper") == "produce"
    assert categorizer.get_category("unknown_exotic_food_123") == "other"
