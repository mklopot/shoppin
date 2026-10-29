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


class ListMode(models.TextChoices):
    """
    Workflow mode for interacting with the shopping list.

    - SHOPPING: In-store execution mode with rapid Got / Skip actions.
    - PANTRY: At-home prep mode with Have / Need / Skip verification.
    """
    SHOPPING = "shopping", "In Store"
    PANTRY = "pantry", "Pantry Check"


class GroupBy(models.TextChoices):
    """
    Grouping strategy for organizing items in the active 'To Buy' section.

    - CATEGORY: Group items by supermarket department/category (e.g. Produce, Dairy).
    - AISLE: Group items by store-specific physical aisle numbers.
    - PRIORITY: Group or sort items by priority (high priority items first).
    """
    CATEGORY = "category", "By Category"
    AISLE = "aisle", "By Aisle"
    PRIORITY = "priority", "By Priority"


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

    @property
    def display_name(self) -> str:
        """
        Return a distinct, human-readable name differentiating this store by branch or address.
        e.g. 'Safeway (2150 S Downing St)' instead of just 'Safeway'.
        """
        raw_name = (self.name or "").strip()
        if any(sep in raw_name for sep in ["#", "(", " - ", "@", "/"]):
            return raw_name
        if self.address:
            clean_addr = (
                self.address.split(",")[0].strip()
                .replace("South ", "S ")
                .replace("North ", "N ")
                .replace("East ", "E ")
                .replace("West ", "W ")
                .replace("Street", "St")
                .replace("Avenue", "Ave")
                .replace("Boulevard", "Blvd")
                .replace("Drive", "Dr")
                .replace("Road", "Rd")
                .replace("Parkway", "Pkwy")
            )
            return f"{raw_name} ({clean_addr})"
        if self.city:
            return f"{raw_name} ({self.city})"
        return raw_name

    def __str__(self) -> str:
        """Return human-readable store name."""
        return self.display_name


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
    workspace = models.ForeignKey(
        "core.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shopping_lists",
        help_text="Workspace this list belongs to",
    )
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
    is_schedule_enabled = models.BooleanField(
        default=False,
        help_text="Whether this preset list automatically refreshes on the primary shopping list",
    )
    interval_days = models.PositiveIntegerField(
        default=7,
        help_text="Recurrence interval in days from last occurrence (default: 7 days / 1 week)",
    )
    last_applied_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the preset list was last applied to the shopping list",
    )
    next_occurrence = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Scheduled timestamp for the next automatic refresh",
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

    def is_due_for_refresh(self, now: timezone.datetime | None = None) -> bool:
        """Return True if this preset list's schedule is active and due to be applied."""
        if not self.is_preset or not self.is_schedule_enabled:
            return False
        if not self.next_occurrence:
            return False
        current_time = now or timezone.now()
        return self.next_occurrence <= current_time

    def compute_next_occurrence(self, base_time: timezone.datetime | None = None) -> timezone.datetime:
        """Compute the next scheduled run datetime based on interval_days."""
        anchor = base_time or self.last_applied_at or timezone.now()
        days = self.interval_days if self.interval_days and self.interval_days > 0 else 7
        return anchor + timezone.timedelta(days=days)


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
    priority = models.BooleanField(
        default=False,
        help_text="Priority item indicated by a burgundy badge",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="For preset lists: whether item is active on automated schedule runs",
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
    source_meal = models.ForeignKey(
        "mealplans.Meal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items",
        help_text="Meal entry this shopping item was added for",
    )
    source_ingredient = models.ForeignKey(
        "recipes.Ingredient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shopping_items",
    )
    source_preset = models.ForeignKey(
        ShoppingList,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_shopping_items",
        help_text="Preset list this shopping item was loaded or scheduled from",
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

    def clean(self) -> None:
        """Validate that shopping item fields are free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    def __str__(self) -> str:
        """Return formatted item quantity, name, and current status."""
        unit_str = f" {self.unit_display}" if self.unit_display else ""
        return f"{self.amount_display}{unit_str} {self.name} [{self.status}]"

    @property
    def amount_display(self) -> str:
        """Return the quantity formatted as a clean fraction or integer string."""
        from apps.core.utils import format_amount
        return format_amount(self.amount)

    @property
    def unit_display(self) -> str:
        """Return the unit properly singularized or pluralized based on the amount."""
        from apps.core.utils import pluralize_unit, singularize_unit
        if not self.amount_unit:
            return ""
        if self.amount == Decimal("1.00") or self.amount == 1:
            return singularize_unit(self.amount_unit)
        return pluralize_unit(self.amount_unit)

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

    @property
    def purpose_display(self) -> str:
        """Return the cleaned purpose without any leading 'For ' or 'for ' prefixes."""
        from apps.core.utils import clean_purpose
        return clean_purpose(self.purpose)

    def save(self, *args, **kwargs):
        """Normalize purpose before saving."""
        from apps.core.utils import clean_purpose
        if self.purpose:
            self.purpose = clean_purpose(self.purpose)
        super().save(*args, **kwargs)

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
        Determine the physical store aisle/department location for this item.

        Checks the target store's mapped aisles (from store chain API or manual entry).
        Leaves blank if the aisle cannot be determined from the store chain API.
        Never returns category names as pseudo-aisles when unmapped.

        Args:
            store: Specific store to check against, or active store on the list.

        Returns:
            Aisle/department string (e.g. 'Aisle 3', 'Produce', 'Meat') or empty string if not determined.
        """
        target_store = store or (self.shopping_list.active_store if self.shopping_list else None)
        if target_store:
            import inflection
            normalized_name = inflection.singularize(self.name.strip().lower())
            aisle_map = target_store.item_aisles.filter(
                item_name_normalized=normalized_name,
                source__in=["api", "manual"],
            ).first()
            if aisle_map and aisle_map.aisle_name:
                clean_aisle = aisle_map.aisle_name.strip()
                return clean_aisle.title() if clean_aisle.isupper() else clean_aisle

            # If not in store_item_aisles, check if item has an explicit manual aisle
            if self.aisle:
                clean_manual = self.aisle.strip()
                if clean_manual.lower() != (self.category or "").strip().lower():
                    return clean_manual.title() if clean_manual.isupper() else clean_manual

            return ""

        if self.aisle:
            clean_manual = self.aisle.strip()
            if clean_manual.lower() != (self.category or "").strip().lower():
                return clean_manual.title() if clean_manual.isupper() else clean_manual

        return ""

    def get_effective_bay(self, store: StoreLocation | None = None) -> str:
        """
        Determine the specific bay number for this item at the target store.

        Returns:
            Bay string (e.g. '7', '14') or empty string if unavailable.
        """
        target_store = store or (self.shopping_list.active_store if self.shopping_list else None)
        if target_store:
            import inflection
            normalized_name = inflection.singularize(self.name.strip().lower())
            aisle_map = target_store.item_aisles.filter(
                item_name_normalized=normalized_name,
                source__in=["api", "manual"],
            ).first()
            if aisle_map and aisle_map.bay_number:
                return aisle_map.bay_number.strip()
        return ""

    def get_effective_location_display(self, store: StoreLocation | None = None) -> str:
        """
        Determine the full user-facing location string, combining aisle and bay if available.

        Returns:
            Formatted location string (e.g. 'Produce Bay 7', 'Aisle 10 Bay 22', 'Meat')
            or empty string if not determined.
        """
        aisle = self.get_effective_aisle(store)
        if not aisle:
            return ""
        bay = self.get_effective_bay(store)
        if bay and "bay" not in aisle.lower():
            return f"{aisle} Bay {bay}"
        return aisle

    @property
    def effective_aisle(self) -> str:
        """Convenience property for template rendering."""
        return self.get_effective_aisle()

    @property
    def effective_bay(self) -> str:
        """Convenience property for template rendering."""
        return self.get_effective_bay()

    @property
    def effective_location_display(self) -> str:
        """Convenience property for template rendering."""
        return self.get_effective_location_display()
