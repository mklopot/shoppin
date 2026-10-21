from django.contrib import admin

from apps.shopping.models import ShoppingList, ShoppingListItem


class ShoppingListItemInline(admin.TabularInline):
    model = ShoppingListItem
    extra = 1


@admin.register(ShoppingList)
class ShoppingListAdmin(admin.ModelAdmin):
    list_display = ("name", "is_preset", "owner", "created_at")
    list_filter = ("is_preset",)
    search_fields = ("name",)
    inlines = [ShoppingListItemInline]


@admin.register(ShoppingListItem)
class ShoppingListItemAdmin(admin.ModelAdmin):
    list_display = ("name", "shopping_list", "amount", "amount_unit", "category", "status", "optional")
    list_filter = ("status", "category", "optional")
    search_fields = ("name", "brand", "vendor", "purpose")
