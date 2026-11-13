import re
import inflection


def parse_amount(amount_with_unit: str) -> tuple[float, str]:
    match = re.search(r"(\d+(?:\.\d*)?|\.\d+)?(.*)", amount_with_unit) 
    if match.groups()[0]:
            amount = float(match[1])
    else:
        amount = 1

    if match.groups()[1]:
        unit = match[2].strip()
    else:
        unit = ""
    return (amount, unit)


def pluralize(word: str) -> str:
    exclusions = ('oz', 'tsp', 'tbsp', 'lb', "C", "c",
            "qt", "fl oz", "fl. oz", "doz", "qt", "pt",
            "pkg", "ml", "l", "L", "gal", "Gal", "Doz")
    exceptions = {"slice": "slices"}
    if word in exclusions:
        return word
    if word in exceptions:
        return exceptions[word]
    return inflection.pluralize(word)


def singularize(word: str) -> str:
    exceptions = {'cloves': 'clove',
                  'slices': 'slice',
                  'slice': 'slice'}
    if word in exceptions:
        return exceptions[word]
    return inflection.singularize(word)
