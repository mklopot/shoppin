from dataclasses import dataclass
import yaml
from yaml.scanner import ScannerError
import logging

from util import parse_amount

logger = logging.getLogger('shoppin.shopping_list_file')

 
class ShoppingListFile:
    def __init__(self, name="") -> None:
        logger.debug(f"Instantiating new {self}")
        self.name = name 
        self.items = []
        self.include = False
        self.path=""

    def load(self, shopping_list_filepath="shopping-list.yaml"):
        self.path = shopping_list_filepath
        logger.info(f'Loading preset file from {self.path}')
        with open(shopping_list_filepath) as f:
            try:
                loaded_items = yaml.safe_load(f)
                # Set preset list name based on its filename
                self.name = shopping_list_filepath.split("/")[-1]
                self.name = self.name.split(".")[0]
                logger.debug(f"Loading preset list {self.name}")
            except ScannerError as e:
                logger.warning(f"Could not parse shopping list from file {shopping_list_filepath}:\n{e}")
            for item in loaded_items:
                if type(item) is str:
                    logger.debug(f"Appending preset item {item}") 
                    self.items.append(Item(name=item,
                        purpose=self.name,
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
                    self.items.append(Item(name=name,
                                           amount=amount,
                                           amount_unit=amount_unit,
                                           optional=optional,
                                           brand=brand,
                                           vendor=vendor,
                                           attribution=self,
                                           purpose=self.name))


    def make_shopping_plan(self):
        return self.items

    def save(self):
        logger.info(f'Saving preset file to {self.path}')
        if not self.path:
            self.path = self.name + ".yaml"
        with open(self.path, 'w') as f:
            for item in self.items:
                if item.optional is False and \
                        item.amount == 1 and not \
                        item.amount_unit and not \
                        item.brand and not \
                        item.vendor:
                    f.write(f"  - {item.name}")
                else:
                    f.write(f"  - {item.name}:")

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

@dataclass
class Item:
    name: str
    attribution: ShoppingListFile 
    purpose: str 
    amount: float = 1
    amount_unit: str = ""
    optional: bool = False
    brand: str = ""
    vendor: str = ""
