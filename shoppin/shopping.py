from enum import Enum
from collections import defaultdict
import uuid


from util import pluralize, singularize

class ItemStatus(Enum):
    NEED = 1
    GOT = 2
    HAVE = 3


class ShoppingList:
    def __init__(self, sequence=None) -> None:
        self.sequence = sequence
        self.items = []

    def load_ingredients(self, ingredients: list) -> None:
        for ingredient in ingredients:
            newitem = ShoppingListItem()
            newitem.from_ingredient(ingredient)
            newitem.list = self
            self.items.append(newitem)
        self.deduplicate()
        self._map()
        self.order()

    def add_item(self, item):
        self.items.append(item)
        item.list = self
        self.deduplicate()
        self._map()
        self.order()

    def deduplicate(self):
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
                    marked_for_deduplication[current_item].append(item)
                else:
                    current_item = item
            else:        
                current_item = item
        for item_to_keep in marked_for_deduplication:
            for duplicate in marked_for_deduplication[item_to_keep]:
                item_to_keep.combine(duplicate)
                self.items.remove(duplicate)

    def _map(self):
        if self.sequence:
            self.mapping = defaultdict(list)
            for item in self.items:
                self.mapping[item.name].append(item)

    def update_sequence(self, item_name):
        if self.sequence:
            self.sequence.update(item_name)
            self.sequence.save()

    def order(self):
        if self.sequence:
            ordered = []
            for name in self.sequence.data:
                if name in self.mapping:
                    ordered.extend(self.mapping[name])
            for name in self.mapping:
                if name not in self.sequence.data:
                    ordered.extend(self.mapping[name])
            self.items = ordered

    def find_by_id(self, item_id):
        result = [item for item in self.items if item.id == item_id]
        if result:
            return result[0]
        return None

    def delete_by_attribution(self, attribution):
        mark_for_deletion = []
        for item in self.items:
            affected_ingredient_list = [ingredient for ingredient in item.ingredients if ingredient.attribution is attribution] 
            if affected_ingredient_list:
                for affected_ingredient in affected_ingredient_list:
                    item.ingredients.remove(affected_ingredient)
                    item.amount -= affected_ingredient.amount
                    if item.amount == 0:
                        mark_for_deletion.append(item)
        for item in mark_for_deletion:
            self.items.remove(item)

    def status_by_attribution(self, recipe):
        status = set()
        status_ignore_optional = set()
        affected_ingredient_list =[item for item in self.items if recipe in [ingredient.attribution for ingredient in item.ingredients]] 
        for item in affected_ingredient_list:
            status.add(item.status)
            if not item.optional:
                status_ignore_optional.add(item.status)
        return status, status_ignore_optional

    def clear(self):
        self.items = []
        self.mapping = {}
        if self.sequence:
            self.sequence.reset_pointer()


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

    def get_purpose(self):
        if self.ingredients:
            print([ingredient.purpose for ingredient in self.ingredients])
            return ', '.join([ingredient.purpose for ingredient in self.ingredients] + self.purpose)
        if self.purpose:
            return ', '.join(self.purpose)

    def from_ingredient(self, ingredient):
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
        if singularize(listitem.name.lower()) == singularize(otheritem.name.lower()) and \
                singularize(listitem.amount_unit) == singularize(otheritem.amount_unit) and\
                listitem.brand.lower() == otheritem.brand.lower() and\
                listitem.vendor.lower() == otheritem.vendor.lower() and\
                listitem.optional == otheritem.optional and\
                listitem.status == otheritem.status and\
                listitem is not otheritem:
            return True
        return False

    def combine(self, other):
        self.amount += other.amount
        self.ingredients.extend(other.ingredients)
        self.purpose = self.purpose + other.purpose
        print("extending purpose", self.purpose)
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
        amount_str = f"{self.amount:.2g}"
        if self.amount == 1:
            return  amount_str + " " + self.amount_unit
        else:
            return  amount_str + " " + pluralize(self.amount_unit)

    def __repr__(self):
        return self.__str__()

    def set_got(self):
        self.status = ItemStatus.GOT
        self.list.update_sequence(self.name.lower())
        self.list.order()

    def set_have(self):
        self.status = ItemStatus.HAVE

    def set_need(self):
        self.status = ItemStatus.NEED

    def lock(self):
        self.locked = True

    def unlock(self):
        self.locked = False
