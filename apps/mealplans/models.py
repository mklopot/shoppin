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
        existing = {d.recipe_id: d for d in self.dishes.select_related("recipe").all()}
        results = []
        for recipe in self.recipes.all():
            if recipe.id in existing:
                results.append(existing[recipe.id])
            else:
                results.append(MealDish(meal=self, recipe=recipe, scale_factor=Decimal("1.00")))
        return results


class MealDish(models.Model):
    """
    An individual recipe dish planned within a meal, tracking portion scaling.
    """
    meal = models.ForeignKey(
        Meal,
        on_delete=models.CASCADE,
        related_name="dishes",
    )
    recipe = models.ForeignKey(
        "recipes.Recipe",
        on_delete=models.CASCADE,
        related_name="meal_dishes",
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
        unique_together = [("meal", "recipe")]

    def __str__(self) -> str:
        """Return formatted dish name with scale factor if scaled."""
        factor_str = f"{self.scale_factor.normalize():f}x" if self.scale_factor != Decimal("1.00") else ""
        return f"{self.recipe.name}{f' ({factor_str})' if factor_str else ''}"

    @property
    def scale_display(self) -> str:
        """Return human-readable scale string like '2x' or '0.5x' (empty if 1x)."""
        if self.scale_factor == Decimal("1.00"):
            return ""
        return f"{self.scale_factor.normalize():f}x"

    @property
    def scaled_portions(self) -> int | float:
        """Return portions adjusted by the scaling factor."""
        base = self.recipe.portions or 4
        scaled = Decimal(str(base)) * self.scale_factor
        if scaled == scaled.to_integral():
            return int(scaled)
        return float(scaled.normalize())
