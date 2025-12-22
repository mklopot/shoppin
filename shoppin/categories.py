import yaml

from util import singularize


class Categorizer:
    def __init__(self, filepath="categories.yaml"):
        self.filepath = filepath
        try:
            self.load()
        except:
            self.categories_index = {}
            self.items_index = {}

    def set(self, item_name, category):
        # normalize input
        item_name = singularize(item_name.lower())
        category = category.lower()
        
        # check for exisitng entry
        # if not matched, delete old entry
        # and add new entry
        if item_name in self.items_index:
            old_category = self.item_index[item_name]
            if category == old_category:
                return
            else:
                del self.items_index[item_name]
                self.categories_index[old_category].remove(item)
                self.items_index[item_name] = category
                if category not in self.categories_index:
                    self.categories_index[category] = [item_name]
                else:
                    self.categories_index[category].append(item_name)
        else:
            # Add new value
            self.items_index[item_name] = category
            if category not in self.categories_index:
                self.categories_index[category] = [item_name]
            else:
                self.categories_index[category].append(item_name)
        self.save()

    def categorize(self, item):
        if item.name in self.items_index:
            item.category = self.items_index[item.name]
        else:
            item.category = "other"
        self.save()

    __call__ = categorize

    def save(self):
        with open(self.filepath, 'w') as f:
            yaml.safe_dump((self.items_index, self.categories_index), f)

    def load(self):
        with open(self.filepath) as f:
            self.items_index, self.categories_index = yaml.safe_load(f)
