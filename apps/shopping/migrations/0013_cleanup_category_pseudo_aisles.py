from django.db import migrations


def cleanup_pseudo_aisles(apps, schema_editor):
    StoreItemAisle = apps.get_model("shopping", "StoreItemAisle")
    ShoppingListItem = apps.get_model("shopping", "ShoppingListItem")

    # 1. Remove all category default pseudo-aisles from store item aisle mappings
    StoreItemAisle.objects.filter(source="default").delete()

    # Known category names that were mistakenly copied into item.aisle
    category_names = {
        "produce", "produce stand", "bakery", "meat", "meat counter",
        "eggs and dairy", "dairy", "cleaning supplies", "trash bags",
        "storage and wrapping", "toilet paper and paper towels", "pantry",
        "canned fruit", "canned goods", "cereal and breakfast", "energy bars",
        "chips and snacks", "condiments", "other", "oil", "spices",
        "skin care and lotions", "rice beans and grains", "baking",
        "canned vegetables", "international foods", "mexican food", "frozen",
    }

    # 2. Reset ShoppingListItem.aisle to blank if it was just the category name
    for item in ShoppingListItem.objects.exclude(aisle=""):
        aisle_clean = item.aisle.strip().lower()
        cat_clean = (item.category or "").strip().lower()
        if aisle_clean == cat_clean or aisle_clean in category_names:
            item.aisle = ""
            item.save(update_fields=["aisle"])


def reverse_cleanup(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0012_seed_nearby_stores"),
    ]

    operations = [
        migrations.RunPython(cleanup_pseudo_aisles, reverse_cleanup),
    ]
