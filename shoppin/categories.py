import pickle

from util import singularize


class Categorizer:
    def __init__(self, filepath):
        self.filepath = filepath
        try:
            self.load()
        except:
            self.categories_index = {}
            self.items_index = {}

    def set(self, item, category):
        # normalize input
        item_name = singularize(item.name.lower())
        category = category.lower()
        
        # check for exisitng entry
        # if not matched, delete old entry
        # and add new entry
        if item_name in self.items_index:
            print("deleting old entry")
            old_category = self.item_index[item_name]
            if category == old_category:
                print("This category already set")
                return
            else:
                print("deleting old entry")
                del self.items_index[item_name]
                self.categories_index[old_category].remove(item)
                self.items_index[item_name] = category
                if category not in self.categories_index:
                    print("Making new category")
                    self.categories_index[category] = [item_name]
                else:
                    print("Creating new category and appending")
                    self.categories_index[category].append(item_name)
        else:
            # Add new value
            self.items_index[item_name] = category
            if category not in self.categories_index:
                self.categories_index[category] = [item_name]
            else:
                self.categories_index[category].append(item_name)
        self.categorize(item)
        self.save()

    def categorize(self, item):
        if item.name in self.items_index:
            item.category = self.items_index[item.name]
        else:
            item.category = "other"
        self.save()

    def save(self):
        with open(self.filepath, 'wb') as f:
            print(f)
            pickle.dump((self.items_index, self.categories_index), f)

    def load(self):
        with open(self.filepath, "rb") as f:
            self.items_index, self.categories_index = pickle.load(f)
