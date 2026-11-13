import os
import glob


import shopping_list_file

class ListManager:
    def __init__(self, dirpath):
        self.lists = []

        for path in glob.glob(os.path.join(dirpath, "*.yaml")):
            newlist = shopping_list_file.ShoppingListFile()
            try:
                newlist.load(path)
            except:
                continue
            self.lists.append(newlist)
