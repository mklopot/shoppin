from enum import Enum
from collections import defaultdict
import uuid
import logging
import datetime
from zoneinfo import ZoneInfo

from util import pluralize, singularize
import categories

logger = logging.getLogger('shoppin.shopping')

class ItemStatus(Enum):
    NEED = 1
    GOT = 2
    HAVE = 3


class ShoppingList:
    def __init__(self, timezone: str ="utc") -> None:
        logger.debug(f"Instantiating new {self}")
        self.items = []
        self.categorizer = None
        self.mapping = defaultdict(list)
        self.categorizer = categories.Categorizer()
        self.timezone = timezone
        logger.debug(f"Using categorizer at {self.categorizer.filepath}")

    def load_ingredients(self, ingredients: list) -> None:
        logger.info("Loading shopping list items from recipe ingredients or preset list")
        for ingredient in ingredients:
            newitem = ShoppingListItem()
            newitem.from_ingredient(ingredient)
            newitem.list = self
            newitem.timezone = self.timezone
            self.items.append(newitem)
            self.categorizer(newitem)
            logger.debug(f"Categorized {newitem.name} as {newitem.category}")
            self.map(newitem)
        self.deduplicate()

    def add_item(self, item):
        logger.info(f"Adding {item.name} to the shopping list")
        self.items.append(item)
        item.list = self
        item.timezone = self.timezone
        self.categorizer(item)
        logger.debug(f"Categorized {item.name} as {item.category}")
        self.map(item)
        self.deduplicate()

    def deduplicate(self):
        logger.debug("De-duplicating shopping list")
        self.items.sort(key=lambda item: (singularize(item.name.lower()),
            singularize(item.amount_unit),
            item.brand,
            item.vendor,
            item.optional))
        marked_for_deduplication = defaultdict(list)
        current_item = None
        for item in self.items:
            if current_item:
                if ShoppingListItem.can_combine(item, current_item): 
                    logger.debug(f"Marking {item.name} for de-duplication with {current_item.name}")
                    marked_for_deduplication[current_item].append(item)
                else:
                    current_item = item
            else:        
                current_item = item
        for item_to_keep in marked_for_deduplication:
            for duplicate in marked_for_deduplication[item_to_keep]:
                item_to_keep.combine(duplicate)
                self.items.remove(duplicate)
                self.unmap(duplicate)

    def map(self, item):
        self.mapping[item.category].append(item)
        logger.debug(f"Mapped categories: {self.mapping.keys()}")
        logger.debug(f"Mapping {item.name} to category {item.category}")

    def unmap(self, item):
        try:
            self.mapping[item.category].remove(item)
        except ValueError:
            pass

    def find_by_id(self, item_id):
        logger.debug(f"Finding item by id {item_id}")
        result = [item for item in self.items if item.id == item_id]
        if result:
            logger.debug(f"Found {result[0].name}")
            return result[0]
        return None

    def delete_by_attribution(self, attribution):
        logger.info(f"Removing shopping list items coming from recipe or preset {attribution.name}")
        mark_for_deletion = []
        for item in self.items:
            affected_ingredient_list = [ingredient for ingredient in item.ingredients if ingredient.attribution is attribution] 
            if affected_ingredient_list:
                for affected_ingredient in affected_ingredient_list:
                    item.ingredients.remove(affected_ingredient)
                    logger.debug(f"Reducing amount of {item.name}")
                    item.amount -= affected_ingredient.amount
                    if item.amount == 0:
                        mark_for_deletion.append(item)
        for item in mark_for_deletion:
            logger.debug(f"Removing {item.name}")
            self.items.remove(item)
            self.mapping[item.category].remove(item)

    def status_by_attribution(self, recipe):
        status = set()
        status_ignore_optional = set()
        affected_item_list =[item for item in self.items if recipe in [ingredient.attribution for ingredient in item.ingredients]] 
        for item in affected_item_list:
            status.add(item.status)
            if not item.optional:
                status_ignore_optional.add(item.status)
        return status, status_ignore_optional

    def clear(self):
        self.items = []
        self.mapping = {}


class ShoppingListItem:
    def __init__(self, name="", amount=1, amount_unit='', brand='', vendor='', optional=False, ingredients=[], purpose=[]):
        self.id = uuid.uuid4().int
        self.name = name
        self.amount = amount
        self.amount_unit = amount_unit
        self.vendor = vendor
        self.brand = brand
        self.optional = optional
        self.ingredients = ingredients
        self.status = ItemStatus.NEED 
        self.list = None
        self.locked = False
        self.purpose = purpose
        self.category = ""
        self.timestamp = datetime.datetime.now()
        self.timezone = "utc"

    def get_purpose(self):
        if self.ingredients:
            purpose = ', '.join([ingredient.purpose for ingredient in self.ingredients] + self.purpose)
            return purpose
        if self.purpose:
            purpose = ', '.join(self.purpose)
            return purpose

    def from_ingredient(self, ingredient):
        logger.debug(f"Populating shopping list item {ingredient.name} data from a recipe ingredient or preset list item")
        self.name = ingredient.name
        self.amount = ingredient.amount
        self.amount_unit = ingredient.amount_unit
        self.vendor = ingredient.vendor
        self.brand = ingredient.brand
        self.optional = ingredient.optional
        self.ingredients = [ingredient]
        self.status = ItemStatus.NEED 
        ingredient.item = self

    @staticmethod
    def can_combine(listitem, otheritem):
        logger.debug(f"Determining if {listitem.name} can stack with {otheritem.name}")
        if singularize(listitem.name.lower()) == singularize(otheritem.name.lower()) and \
                singularize(listitem.amount_unit) == singularize(otheritem.amount_unit) and\
                listitem.brand.lower() == otheritem.brand.lower() and\
                listitem.vendor.lower() == otheritem.vendor.lower() and\
                listitem.optional == otheritem.optional and\
                listitem.status == otheritem.status and\
                listitem is not otheritem:
            logger.debug("Can stack")
            return True
        logger.debug("Cannot stack")
        return False

    def combine(self, other):
        logger.debug(f"Stacking {self.name} with {other.name}")
        self.amount += other.amount
        logger.debug(f"Ingredients of first instance: {self.ingredients}")
        logger.debug(f"Ingredients of second instance: {other.ingredients}")
        self.ingredients.extend(other.ingredients)
        logger.debug(f"Extending ingredients to {self.ingredients}")
        self.purpose = self.purpose + other.purpose
        logger.debug(f"Extending purpose to {self.purpose}")
        for ingredient in self.ingredients:
            ingredient.item = self

    def __str__(self):
        result = self.name
        amount_str = f"{self.amount:.2g}"
        if self.amount != 1:
            result += "\n    " + amount_str + " " + pluralize(self.amount_unit)
        else:
            result += "\n    " + amount_str + " " + self.amount_unit
        if self.optional:
            result += "\n    optional"
        if self.brand:
            result += "\n    brand: " + self.brand  
        if self.vendor:
            result += "\n    best vendor: " + self.vendor  
        recipe_names = [ingredient.attribution.name for ingredient in self.ingredients]
        result += "\n    For " + self.get_purpose()
        return result

    def get_amount_with_unit(self):
        if self.amount < 100:
            amount_str = f"{self.amount:.2g}"
        else:
            amount_str = str(self.amount).rstrip('0').rstrip('.')

        if self.amount == 1:
            return  amount_str + " " + self.amount_unit
        else:
            return  amount_str + " " + pluralize(self.amount_unit)

    def get_timestamp(self):
        return self.timestamp.strftime("%m/%d/%y")

    def __repr__(self):
        return self.__str__()

    def set_got(self):
        logger.debug(f"Setting {self.name} item status to GOT")
        self.status = ItemStatus.GOT
        self.timestamp = datetime.datetime.now(ZoneInfo(self.timezone))

    def set_have(self):
        logger.debug(f"Setting {self.name} item status to HAVE")
        self.status = ItemStatus.HAVE
        self.timestamp = datetime.datetime.now(ZoneInfo(self.timezone))

    def set_need(self):
        logger.debug(f"Setting {self.name} item status to NEED")
        self.status = ItemStatus.NEED
        self.timestamp = datetime.datetime.now(ZoneInfo(self.timezone))

    def lock(self):
        logger.debug(f"Setting {self.name} item lock status to LOCKED")
        self.locked = True

    def unlock(self):
        logger.debug(f"Setting {self.name} item lock status to UNLOCKED")
        self.locked = False
