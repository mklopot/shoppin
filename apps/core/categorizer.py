"""
Grocery item categorization engine.

Maps item names (e.g., 'bell pepper', 'organic whole milk') to grocery departments/categories
(e.g., 'produce', 'dairy') using a predefined YAML dictionary and keyword heuristics.
"""

from collections import Counter
from pathlib import Path

import inflection
import yaml

DEFAULT_CATEGORIES_FILE = Path(__file__).resolve().parent.parent.parent / "legacy" / "categories.yaml"


class Categorizer:
    """
    In-memory classifier that infers department categories for grocery items.

    Reads a YAML dataset containing a dictionary of known items mapped to categories,
    and classifies arbitrary item strings using exact matches, partial keyword tallies,
    and head-noun tie-breaking heuristics.
    """

    def __init__(self, filepath: Path | str = DEFAULT_CATEGORIES_FILE) -> None:
        """
        Initialize the categorizer with a path to a categories YAML file.

        Args:
            filepath: Path to the YAML file mapping items to categories.
        """
        self.filepath = Path(filepath)
        self.items_index: dict[str, str] = {}
        self.categories_index: dict[str, list[str]] = {}
        self.load()

    def load(self) -> None:
        """
        Load and parse the categories YAML file into indexed lookup dictionaries.
        Safely handles missing files or parsing errors by falling back to empty indices.
        """
        if not self.filepath.exists():
            return
        try:
            with open(self.filepath, encoding="utf-8") as file_handle:
                data = yaml.safe_load(file_handle)
                if isinstance(data, (list, tuple)) and len(data) >= 2:
                    raw_items = data[0] or {}
                    self.items_index = {
                        key.replace("%", " ").strip().lower(): val
                        for key, val in raw_items.items()
                    }
                    self.categories_index = data[1] or {}
        except Exception:
            self.items_index = {}
            self.categories_index = {}

    def get_category(self, item_name: str) -> str:
        """
        Determine the most appropriate category for a given item name.

        Args:
            item_name: The raw or normalized grocery item name (e.g. 'bell peppers').

        Returns:
            The matched category name string (e.g. 'produce'), or 'other' if unclassified.
        """
        if not item_name:
            return "other"
        clean_name = inflection.singularize(item_name.strip().lower())

        # Exact match in known items index
        if clean_name in self.items_index:
            return self.items_index[clean_name]

        # Partial/keyword match: tally occurrences across all matching items
        category_counts: Counter[str] = Counter()
        for known_item, category in self.items_index.items():
            if known_item in clean_name or clean_name in known_item:
                category_counts[category] += 1

        if category_counts:
            # Pick the category with the highest tally of keyword matches
            most_common = category_counts.most_common()
            max_count = most_common[0][1]
            top_candidates = [category for category, count in most_common if count == max_count]

            if len(top_candidates) == 1:
                return top_candidates[0]

            # In case of tie, prefer the category where clean_name matches the head noun (last word)
            for candidate in top_candidates:
                for known_item, category in self.items_index.items():
                    if category == candidate and (
                        known_item.endswith(clean_name) or clean_name == known_item.split()[-1]
                    ):
                        return candidate

            return top_candidates[0]

        return "other"


# Global singleton instance
categorizer = Categorizer()
