"""
Django admin configuration for shopping models.

Provides administrative list displays, filters, search, and inlines for
StoreLocation, StoreItemAisle, ShoppingList, and ShoppingListItem.
"""

from django.contrib import admin

from apps.shopping.models import ShoppingList, ShoppingListItem, StoreItemAisle, StoreLocation


class ShoppingListItemInline(admin.TabularInline):
    """Inline admin editor for shopping list items inside a shopping list."""
    model = ShoppingListItem
    extra = 1


class StoreItemAisleInline(admin.TabularInline):
    """Inline admin editor for store aisle mappings inside a store location."""
    model = StoreItemAisle
    extra = 1


@admin.register(StoreLocation)
class StoreLocationAdmin(admin.ModelAdmin):
    """Admin manager for supermarket locations."""
    list_display = ("name", "chain", "city", "state", "external_store_id")
    list_filter = ("chain", "state")
    search_fields = ("name", "address", "city", "external_store_id")
    inlines = [StoreItemAisleInline]


@admin.register(StoreItemAisle)
class StoreItemAisleAdmin(admin.ModelAdmin):
    """Admin manager for learned or API-cached store item aisle sequences."""
    list_display = ("item_name_normalized", "store", "aisle_name", "bay_number", "sequence_order", "source")
    list_filter = ("store", "source")
    search_fields = ("item_name_normalized", "aisle_name")


@admin.register(ShoppingList)
class ShoppingListAdmin(admin.ModelAdmin):
    """Admin manager for shopping lists."""
    list_display = ("name", "is_preset", "active_store", "owner", "created_at")
    list_filter = ("is_preset", "active_store")
    search_fields = ("name",)
    inlines = [ShoppingListItemInline]


@admin.register(ShoppingListItem)
class ShoppingListItemAdmin(admin.ModelAdmin):
    """Admin manager for individual shopping list items and status tracking."""
    list_display = (
        "name",
        "shopping_list",
        "amount",
        "amount_unit",
        "category",
        "aisle",
        "status",
        "optional",
        "status_changed_at",
        "status_changed_by",
    )
    list_filter = ("status", "category", "optional", "status_changed_by")
    search_fields = ("name", "brand", "vendor", "purpose", "aisle", "status_changed_by_name")
