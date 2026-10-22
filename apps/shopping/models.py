"""
Data models for shopping lists, items, and supermarket store locations.

Supports multi-mode shopping (In-Store execution vs Pantry Check),
store-specific aisle sequence learning, and state transitions.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class ItemStatus(models.TextChoices):
    """
    Workflow states for items on a shopping list.

    - NEED: To Buy (active item needed for this shopping trip).
    - GOT: In Cart (purchased during shopping trip).
    - HAVE: Already Have (verified at home in the pantry).
    - DONT_NEED: Skipped (deferred or not needed today).
    """
    NEED = "NEED", "Need"
    GOT = "GOT", "Got"
    HAVE = "HAVE", "Already Have"
    DONT_NEED = "DONT_NEED", "Don't Actually Need"


class StoreLocation(models.Model):
    """
    A physical supermarket location (e.g. King Soopers, Safeway) with geolocation.

    Used to map grocery items to specific aisle numbers and compute optimal
    in-store walking sequence orders.
    """
    CHAIN_CHOICES = [
        ("kroger", "Kroger / King Soopers"),
        ("safeway", "Safeway"),
        ("whole_foods", "Whole Foods"),
        ("other", "Other / Local Market"),
    ]

    name = models.CharField(max_length=255, help_text="e.g. 'King Soopers #01400943 - Glendale'")
    chain = models.CharField(max_length=50, choices=CHAIN_CHOICES, default="kroger")
    external_store_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Store ID in chain API (e.g. Kroger locationId '01400943')",
    )
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True, default="CO")
    zip_code = models.CharField(max_length=20, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chain", "name"]

    def __str__(self) -> str:
        """Return human-readable store name and chain display."""
        return f"{self.name} ({self.get_chain_display()})"


class StoreItemAisle(models.Model):
    """
    Cached mapping of an item name to an aisle number/description at a store.

    Populated automatically via store APIs (such as Kroger) or learned organically
    when users manually edit an item's aisle location.
    """
    SOURCE_CHOICES = [
        ("api", "Kroger API"),
        ("manual", "User Entered"),
        ("default", "Category Default"),
    ]

    store = models.ForeignKey(
        StoreLocation,
        on_delete=models.CASCADE,
        related_name="item_aisles",
    )
    item_name_normalized = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Normalized lowercase singular item name (e.g. 'black bean', 'milk')",
    )
    aisle_name = models.CharField(
        max_length=100,
        help_text="e.g. 'Aisle 14', 'Produce', 'Deli'",
    )
    bay_number = models.CharField(max_length=50, blank=True)
    sequence_order = models.PositiveIntegerField(
        default=100,
        help_text="Walking sequence order (lower = closer to store entrance)",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="api")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("store", "item_name_normalized")
        ordering = ["sequence_order", "aisle_name"]

    def __str__(self) -> str:
        """Return mapping representation string."""
        return f"{self.item_name_normalized} -> {self.aisle_name} @ {self.store.name}"


class ShoppingList(models.Model):
    """
    A shopping list container containing items to purchase or check in the pantry.

    Can be marked as a reusable preset template (e.g. 'Spices', 'Pantry Staples')
    or serve as the primary active household shopping list.
    """
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
    active_store = models.ForeignKey(
        StoreLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_shopping_lists",
        help_text="Current store selected for aisle lookups and walking order",
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
    custom_section_order = models.JSONField(
        default=dict,
        blank=True,
        help_text="Custom order of categories and aisles: {'category': [...], 'aisle': [...]}",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["is_preset", "name"]

    def __str__(self) -> str:
        """Return the list name with preset flag if applicable."""
        return f"{self.name}{' (Preset)' if self.is_preset else ''}"


class ShoppingListItem(models.Model):
    """
    An individual product or ingredient on a shopping list.

    Tracks quantity, brand/vendor preferences, store aisle locations,
    item triage status (NEED, GOT, HAVE, DONT_NEED), and status change audit metadata.
    """
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
    purpose = models.CharField(
        max_length=255,
        blank=True,
        default="one-time purchase",
        help_text="Human-readable purpose (defaults to 'one-time purchase' for one-offs)",
    )
    optional = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=ItemStatus.choices,
        default=ItemStatus.NEED,
    )
    locked = models.BooleanField(
        default=False,
        help_text="Whether this item is confirmed needed during Pantry Check",
    )
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
    status_changed_at = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp when item was placed in current section or changed state",
    )
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items_status_changed",
        help_text="User who last updated or placed the item in this section",
    )
    status_changed_by_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Display name of who changed the item status or state",
    )

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        """Return formatted item quantity, name, and current status."""
        unit_str = f" {self.amount_unit}" if self.amount_unit else ""
        return f"{self.amount:g}{unit_str} {self.name} [{self.status}]"

    @property
    def changed_by_display(self) -> str:
        """
        Return the username of who changed status, falling back to 'unknown' if anonymous.
        Never returns 'You'.
        """
        if self.status_changed_by:
            return self.status_changed_by.username
        if self.status_changed_by_name and self.status_changed_by_name.lower() != "you":
            return self.status_changed_by_name
        return "unknown"

    def reduce_or_delete(self, amount_to_subtract: Decimal) -> "ShoppingListItem | None":
        """
        Subtract amount from this item. If amount reaches zero or less, deletes the item.

        Args:
            amount_to_subtract: The quantity to reduce.

        Returns:
            The updated item instance, or None if deleted.
        """
        new_amount = self.amount - amount_to_subtract
        if new_amount <= Decimal("0.00"):
            self.delete()
            return None
        self.amount = new_amount
        self.save(update_fields=["amount", "updated_at"])
        return self

    def get_effective_aisle(self, store: StoreLocation | None = None) -> str:
        """
        Determine the effective aisle name for sorting.

        Checks store-specific mapped aisles first, then item's saved aisle,
        falling back to title-cased category.

        Args:
            store: Specific store to check against, or active store on the list.

        Returns:
            Aisle name string (e.g. 'Aisle 3', 'Produce').
        """
        target_store = store or self.shopping_list.active_store
        if target_store:
            import inflection
            normalized_name = inflection.singularize(self.name.strip().lower())
            aisle_map = target_store.item_aisles.filter(item_name_normalized=normalized_name).first()
            if aisle_map:
                return aisle_map.aisle_name
        return self.aisle or self.category.title()
