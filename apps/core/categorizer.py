from pathlib import Path

import inflection
import yaml

DEFAULT_CATEGORIES_FILE = Path(__file__).resolve().parent.parent.parent / "legacy" / "categories.yaml"


class Categorizer:
    def __init__(self, filepath=DEFAULT_CATEGORIES_FILE):
        self.filepath = Path(filepath)
        self.items_index = {}
        self.categories_index = {}
        self.load()

    def load(self):
        if not self.filepath.exists():
            return
        try:
            with open(self.filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, (list, tuple)) and len(data) >= 2:
                    self.items_index = data[0] or {}
                    self.categories_index = data[1] or {}
        except Exception:
            self.items_index = {}
            self.categories_index = {}

    def get_category(self, item_name: str) -> str:
        if not item_name:
            return "other"
        clean_name = inflection.singularize(item_name.strip().lower())

        # Exact match
        if clean_name in self.items_index:
            return self.items_index[clean_name]

        # Partial/keyword match
        for known_item, cat in self.items_index.items():
            if known_item in clean_name or clean_name in known_item:
                return cat

        return "other"


# Global singleton instance
categorizer = Categorizer()
