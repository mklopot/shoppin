from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError


from util import parse_amount


@dataclass
class Section:
    name: str
    items: list["Item"]

@dataclass
class Item:
    name: str
    attribution: Section
    amount: float = 1
    amount_unit: str = ""
    optional: bool = False
    brand: str = ""
    vendor: str = ""
 
class ShoppingListFile:
    def __init__(self, sections: list[Section] = {}) -> None:
        self.sections = sections

    def load(self, shopping_list_filepath="shopping-list.yaml"):
        with open(shopping_list_filepath) as f:
            try:
                loaded_sections = yaml.safe_load(f)
            except Exception as e:
                print("Could not parse shopping list from file ", shopping_list_filepath, ":\n", e)
        for loaded_section in loaded_sections:
            items = []
            loaded_items = loaded_sections[loaded_section]
            self.sections[loaded_section] = (Section(name=loaded_section,
                                                  items=[]))
            for item in loaded_items:
                if type(item) is str:
                    items.append(Item(name=item, attribution=self.sections[loaded_section]))
                else:
                    name = list(item.keys())[0].strip()
                    amount_with_unit = str(item[name].get("amount", "1"))
                    amount, amount_unit = parse_amount(amount_with_unit)
                    amount_unit = amount_unit.strip()
                    optional = item[name].get("optional", False)
                    brand = item[name].get("brand", "").strip()
                    vendor = item[name].get("vendor", "").strip()
                    items.append(Item(name=name,
                                      amount=amount,
                                      amount_unit=amount_unit,
                                      optional=optional,
                                      brand=brand,
                                      vendor=vendor,
                                      attribution=self.sections[loaded_section]))

            self.sections[loaded_section].items = items

    def make_shopping_plan(self):
        items_list = []
        for section in self.sections:
            for item in self.sections[section].items:
                    items_list.append(item)
        return items_list
