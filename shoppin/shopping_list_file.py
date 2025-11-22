from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError
import logging

from util import parse_amount

logger = logging.getLogger('shoppin.shopping_list_file')

@dataclass
class Section:
    name: str
    items: list["Item"]

 
class ShoppingListFile:
    def __init__(self) -> None:
        logger.debug(f"Instantiating new {self}")
        self.sections = {}
        self.name = ""
        self.include = False
        self.path=""

    def load(self, shopping_list_filepath="shopping-list.yaml"):
        self.path = shopping_list_filepath
        with open(shopping_list_filepath) as f:
            try:
                loaded_sections = yaml.safe_load(f)
                self.name = shopping_list_filepath.split("/")[-1]
                self.name = self.name.split(".")[0]
            except ScannerError as e:
                logger.warning(f"Could not parse shopping list from file {shopping_list_filepath}:\n{e}")
        for loaded_section in loaded_sections:
            items = []
            loaded_items = loaded_sections[loaded_section]
            logger.debug(f"Loading preset list section {loaded_section}")
            self.sections[loaded_section] = (Section(name=loaded_section,
                                                  items=[]))
            for item in loaded_items:
                if type(item) is str:
                    logger.debug(f"Appending preset item {item}") 
                    items.append(Item(name=item,
                        purpose=self.sections[loaded_section].name,
                        attribution=self))
                else:
                    name = list(item.keys())[0].strip()
                    amount_with_unit = str(item[name].get("amount", "1"))
                    amount, amount_unit = parse_amount(amount_with_unit)
                    amount_unit = amount_unit.strip()
                    optional = item[name].get("optional", False)
                    brand = item[name].get("brand", "").strip()
                    vendor = item[name].get("vendor", "").strip()
                    logger.debug(f"Appending preset item {name}") 
                    items.append(Item(name=name,
                                      amount=amount,
                                      amount_unit=amount_unit,
                                      optional=optional,
                                      brand=brand,
                                      vendor=vendor,
                                      attribution=self,
                                      purpose=self.sections[loaded_section].name))

            self.sections[loaded_section].items = items

    def make_shopping_plan(self):
        items_list = []
        for section in self.sections:
            for item in self.sections[section].items:
                    items_list.append(item)
        return items_list

    def save(self):
        if not self.path:
            return
        with open(self.path, 'w') as f:
            for section in self.sections:
                f.write(section.name+":")
                for item in self.recipes[recipe].items:
                    if item.optional is False and \
                            item.amount == 1 and not \
                            item.amount_unit and not \
                            item.brand and not \
                            item.vendor:
                        f.write(f"  - {item.name}\n")
                    else:
                        f.write(f"  - {item.name}:\n")

                        if item.amount != 1 or item.amount_unit:
                            f.write(f"      amount: {item.amount:.2g}")
                            if item.amount_unit:
                                f.write(f" {item.amount_unit}")
                            f.write("\n")
                    if item.optional:
                        f.write("      optional: True\n")
                    if item.brand:
                        f.write(f"      brand: {item.brand}\n")
                    if item.vendor:
                        f.write(f"      vendor: {item.vendor}\n")
                    f.write("\n")
                f.write("\n")

@dataclass
class Item:
    name: str
    attribution: ShoppingListFile 
    purpose: Section
    amount: float = 1
    amount_unit: str = ""
    optional: bool = False
    brand: str = ""
    vendor: str = ""
