import re


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



