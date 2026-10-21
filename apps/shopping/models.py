from decimal import Decimal

from django.conf import settings
from django.db import models


class ItemStatus(models.TextChoices):
    NEED = "NEED", "Need"
    GOT = "GOT", "Got"
    HAVE = "HAVE", "Already Have"
    DONT_NEED = "DONT_NEED", "Don't Actually Need"


class ShoppingList(models.Model):
    name = models.CharField(max_length=255, default="Main Shopping List")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_lists",
    )
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="shared_shopping_lists",
    )
    is_preset = models.BooleanField(
        default=False,
        help_text="True if this is a reusable preset list template (e.g. Spices, Breakfasts)",
    )
    auto_refresh_schedule = models.CharField(
        max_length=100,
        blank=True,
        help_text="Cron expression or schedule description (e.g. 'weekly-saturday')",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["is_preset", "name"]

    def __str__(self):
        return f"{self.name}{' (Preset)' if self.is_preset else ''}"


class ShoppingListItem(models.Model):
    shopping_list = models.ForeignKey(
        ShoppingList,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=255)
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Item quantity",
    )
    amount_unit = models.CharField(max_length=50, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    vendor = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=100, blank=True, default="other")
    aisle = models.CharField(max_length=100, blank=True, help_text="Store aisle location")
    purpose = models.CharField(max_length=255, blank=True)
    optional = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.NEED,
    )
    locked = models.BooleanField(default=False)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Sort order for drag-and-drop reordering",
    )

    source_recipe = models.ForeignKey(
        "recipes.Recipe",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items",
    )
    source_ingredient = models.ForeignKey(
        "recipes.Ingredient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        unit_str = f" {self.amount_unit}" if self.amount_unit else ""
        return f"{self.amount:g}{unit_str} {self.name} [{self.status}]"

    def reduce_or_delete(self, amount_to_subtract: Decimal):
        """
        Safely reduces item amount or removes the item if amount drops to <= 0.
        Prevents negative quantity bugs.
        """
        new_amount = self.amount - amount_to_subtract
        if new_amount <= Decimal("0.00"):
            self.delete()
            return None
        self.amount = new_amount
        self.save(update_fields=["amount", "updated_at"])
        return self
