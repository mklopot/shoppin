from collections import Counter
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
                    raw_items = data[0] or {}
                    self.items_index = {
                        k.replace("%", " ").strip().lower(): v
                        for k, v in raw_items.items()
                    }
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

        # Partial/keyword match: tally occurrences across all matching items
        category_counts = Counter()
        for known_item, cat in self.items_index.items():
            if known_item in clean_name or clean_name in known_item:
                category_counts[cat] += 1

        if category_counts:
            # Pick the category with the biggest count
            most_common = category_counts.most_common()
            max_count = most_common[0][1]
            top_candidates = [cat for cat, count in most_common if count == max_count]

            if len(top_candidates) == 1:
                return top_candidates[0]

            # In case of tie, prefer category where clean_name matches the head noun (last word)
            for cand in top_candidates:
                for known_item, cat in self.items_index.items():
                    if cat == cand and (known_item.endswith(clean_name) or clean_name == known_item.split()[-1]):
                        return cand

            return top_candidates[0]

        return "other"


# Global singleton instance
categorizer = Categorizer()
