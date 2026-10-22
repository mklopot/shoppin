"""
Data models for meal planning, meal composition, and scheduling rules.

Enables grouping recipes into meals (e.g. 'Monday Dinner') and tracking
rules (e.g. 'every dinner needs a veggie protein').
"""

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

    def __str__(self) -> str:
        """Return formatted meal name with emoji prefix."""
        return f"{self.emoji} {self.name}".strip()
