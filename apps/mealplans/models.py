"""
Data models for meal planning, meal composition, and scheduling rules.

Enables grouping recipes into meals (e.g. 'Monday Dinner') and tracking
rules (e.g. 'every dinner needs a veggie protein').
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class MealPlan(models.Model):
    """
    A named meal plan schedule containing scheduled meals and dietary rules.
    """
    name = models.CharField(max_length=255)
    workspace = models.ForeignKey(
        "core.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meal_plans",
        help_text="Workspace this meal plan belongs to",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        """Validate that meal plan name is free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    def __str__(self) -> str:
        """Return the meal plan name."""
        return self.name


class MealPlanRule(models.Model):
    """
    A validation or guideline rule for constructing balanced meal plans.
    """
    meal_plan = models.ForeignKey(
        MealPlan,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    rule_text = models.CharField(
        max_length=255,
        help_text="e.g. 'every dinner needs veggie protein'",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        """Validate that rule text is free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    def __str__(self) -> str:
        """Return the rule description text."""
        return self.rule_text


class Meal(models.Model):
    """
    An individual planned meal (e.g. 'Monday Dinner', 'Sunday Brunch') consisting of recipes.
    """
    meal_plan = models.ForeignKey(
        MealPlan,
        on_delete=models.CASCADE,
        related_name="meals",
    )
    name = models.CharField(max_length=255, help_text="e.g. 'Monday Dinner'")
    emoji = models.CharField(max_length=10, blank=True)
    order = models.PositiveIntegerField(default=0)
    recipes = models.ManyToManyField(
        "recipes.Recipe",
        blank=True,
        related_name="meal_entries",
    )

    class Meta:
        ordering = ["order", "id"]

    def save(self, *args, **kwargs) -> None:
        """Auto-populate emoji if not provided."""
        if not self.emoji:
            from apps.mealplans.services.emojifier import get_meal_emoji
            self.emoji = get_meal_emoji(self.name)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate that meal plan name is free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    def __str__(self) -> str:
        """Return formatted meal name with emoji prefix."""
        return f"{self.emoji} {self.name}".strip()

    @property
    def dishes_list(self) -> list["MealDish"]:
        """
        Return list of MealDish objects, preserving order and falling back gracefully
        if a recipe is attached in M2M without an explicit MealDish record.
        """
        dishes = list(self.dishes.select_related("recipe").all())
        if dishes:
            return dishes
        results = []
        for recipe in self.recipes.all():
            results.append(MealDish(meal=self, recipe=recipe, scale_factor=Decimal("1.00")))
        return results


class MealDish(models.Model):
    """
    An individual planned entry within a meal: either a Recipe dish (tracking portion scaling)
    or a standalone single ingredient / shopping list item (when recipe is None).
    """
    meal = models.ForeignKey(
        Meal,
        on_delete=models.CASCADE,
        related_name="dishes",
    )
    recipe = models.ForeignKey(
        "recipes.Recipe",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="meal_dishes",
    )
    item_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Name of standalone ingredient or shopping item when not a recipe dish",
    )
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Base quantity for standalone single item",
    )
    amount_unit = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Unit of measurement for standalone single item",
    )
    scale_factor = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Portion scaling factor (e.g. 0.5 for half, 2.0 for double)",
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "created_at", "id"]

    def clean(self) -> None:
        """Validate that single item fields are free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    @property
    def is_single_item(self) -> bool:
        """Return True if this meal entry is a standalone single shopping item rather than a recipe."""
        return self.recipe_id is None

    @property
    def display_name(self) -> str:
        """Return the human-readable name of the recipe dish or single item."""
        if self.recipe_id and self.recipe:
            return self.recipe.name
        return self.item_name

    @property
    def effective_amount(self) -> Decimal:
        """Return the scaled quantity for a standalone single item."""
        base = self.amount if self.amount is not None else Decimal("1.00")
        factor = self.scale_factor if self.scale_factor is not None else Decimal("1.00")
        return (base * factor).quantize(Decimal("0.01"))

    @property
    def amount_display(self) -> str:
        """Return formatted quantity string for a standalone single item."""
        from apps.core.utils import format_amount
        return format_amount(self.effective_amount)

    @property
    def unit_display(self) -> str:
        """Return singularized or pluralized unit for a standalone single item."""
        from apps.core.utils import pluralize_unit, singularize_unit
        if not self.amount_unit:
            return ""
        eff = self.effective_amount
        if eff == Decimal("1.00") or eff == 1:
            return singularize_unit(self.amount_unit)
        return pluralize_unit(self.amount_unit)

    @property
    def quantity_display(self) -> str:
        """Return combined formatted amount and unit for a standalone single item."""
        unit_str = self.unit_display
        return f"{self.amount_display} {unit_str}".strip() if unit_str else self.amount_display

    def __str__(self) -> str:
        """Return formatted dish or single item name with scale factor if scaled."""
        if self.is_single_item:
            qty = self.quantity_display
            return f"{self.item_name} ({qty})" if qty else self.item_name
        factor_str = f"{self.scale_factor.normalize():f}x" if self.scale_factor != Decimal("1.00") else ""
        return f"{self.recipe.name}{f' ({factor_str})' if factor_str else ''}"

    @property
    def scale_factor_display_val(self) -> str:
        """Return formatted scale number like '1' or '1.5' or '2' for inputs."""
        normalized = self.scale_factor.normalize()
        if normalized == normalized.to_integral():
            return str(int(normalized))
        return f"{normalized:f}"

    @property
    def scale_display(self) -> str:
        """Return human-readable scale string like '2x' or '0.5x' (empty if 1x)."""
        if self.scale_factor == Decimal("1.00"):
            return ""
        return f"{self.scale_factor.normalize():f}x"

    @property
    def scaled_portions(self) -> int | float:
        """Return portions adjusted by the scaling factor."""
        if not self.recipe:
            eff = self.effective_amount
            if eff == eff.to_integral():
                return int(eff)
            return float(eff.normalize())
        base = self.recipe.portions or 4
        scaled = Decimal(str(base)) * self.scale_factor
        if scaled == scaled.to_integral():
            return int(scaled)
        return float(scaled.normalize())

    @property
    def is_recipe_updated_since_added(self) -> bool:
        """
        Check if the underlying recipe was updated after this dish was planned in the meal.
        """
        if not self.created_at or not self.recipe or not self.recipe.updated_at:
            return False
        return (self.recipe.updated_at - self.created_at).total_seconds() > 1
