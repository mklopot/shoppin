from enum import Enum
from collections import defaultdict

from util import pluralize, singularize

class ItemStatus(Enum):
    NEED = 1
    GOT = 2
    HAVE = 3
    HAVE_PARTIAL = 4


class ShoppingList:
    def __init__(self, sequence=None) -> None:
        self.sequence = sequence
        self.ingredients = []

    def load_ingredients(self, ingredients: list) -> None:
        for ingredient in ingredients:
            newitem = ShoppingListItem(ingredient)
            newitem.list = self
            self.ingredients.append(newitem)
        self.deduplicate()
        self._map()

    def deduplicate(self):
        self.ingredients.sort(key=lambda item: (singularize(item.name.lower()),
                                                singularize(item.amount_unit),
                                                item.brand,
                                                item.vendor,
                                                item.optional))
        marked_for_deduplication = defaultdict(list)
        current_item = None
        print("current item:", current_item)
        for item in self.ingredients:
            print("Processing", item.name, id(item))
            if current_item:
                print("comparing items:", current_item.name, id(current_item), "&&", item.name, id(item))
                if ShoppingListItem.can_combine(item, current_item): 
                    print("found matching ingredients:", item.name, current_item.name)
                    # if current_item.combine(item):
                        # self.ingredients.remove(item)
                    marked_for_deduplication[current_item].append(item)
                    print("marked duplicate for deduplication:", item.name, id(item))
                else:
                    current_item = item
                    print("moving to next type of ingredient")
            else:        
                current_item = item
                print("this is the first item:", item.name)
        for item_to_keep in marked_for_deduplication:
            for duplicate in marked_for_deduplication[item_to_keep]:
                item_to_keep.combine(duplicate)
                self.ingredients.remove(duplicate)

    def _map(self):
        if self.sequence:
            self.mapping = {}
            for item in self.ingredients:
                self.mapping[item.name] = item

    def update_sequence(self, item_name):
        if self.sequence:
            self.sequence.update(item_name)

    def order(self, sequence):
        if self.sequence:
            ordered = []
            for item in self.sequence:
                if item in self.mapping:
                    ordered.append(self.mapping["item"])
            self.ingredients = ordered

class ShoppingListItem:
    def __init__(self, ingredient):
        self.list = None
        self.name = ingredient.name
        self.amount = ingredient.amount
        self.amount_unit = ingredient.amount_unit
        self.vendor = ingredient.vendor
        self.brand = ingredient.brand
        self.optional = ingredient.optional
        self.ingredients = [ingredient]
        ingredient.shopping_list_item = self
        self.status = ItemStatus.NEED 

    @staticmethod
    def can_combine(listitem, otheritem):
        if singularize(listitem.name.lower()) == singularize(otheritem.name.lower()) and \
                singularize(listitem.amount_unit) == singularize(otheritem.amount_unit) and\
                listitem.brand.lower() == otheritem.brand.lower() and\
                listitem.vendor.lower() == otheritem.vendor.lower() and\
                listitem.optional == otheritem.optional and\
                listitem is not otheritem:
            return True
        return False

    def combine(self, other):
        self.amount += other.amount
        self.ingredients.extend(other.ingredients)

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
        result += "\n    For " + ", ".join(recipe_names)
        return result

    def __repr__(self):
        return self.__str__()

    def set_got(self):
        self.status = ItemStatus.GOT
        self.list.update_sequence(self.name.lower())
        self.list.order()

    def set_have(self):
        self.status = ItemStatus.HAVE
        self.list.update_sequence(self.name.lower())
        self.list.order()

    def set_need(self):
        self.status = ItemStatus.NEED
        self.list.update_sequence(self.name.lower())
        self.list.order()
