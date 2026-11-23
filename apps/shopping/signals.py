"""
Django signals for maintaining shopping list item attribution integrity.

Ensures that when a Recipe, Meal, or Preset ShoppingList is deleted directly,
affected ShoppingListItem records are recalculated or cleared of orphaned source
links so standalone items remain eligible for retention cleanup.
"""

from typing import Any

from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.mealplans.models import Meal
from apps.recipes.models import Recipe
from apps.shopping.models import ShoppingList, ShoppingListItem, ShoppingListItemSource


def _capture_affected_items(
    instance: Any,
    source_filter: dict[str, Any],
    legacy_filter: dict[str, Any],
) -> None:
    """Capture ShoppingListItem IDs referencing a deleted origin before CASCADE/SET_NULL runs."""
    instance._cleanup_attr_item_ids = list(
        ShoppingListItemSource.objects.filter(**source_filter)
        .values_list("item_id", flat=True)
        .distinct()
    )
    instance._cleanup_legacy_item_ids = list(
        ShoppingListItem.objects.filter(**legacy_filter, attributions__isnull=True)
        .values_list("id", flat=True)
        .distinct()
    )


def _reconcile_affected_items(instance: Any, clear_fields: dict[str, Any]) -> None:
    """Recalculate or clear orphaned source links on ShoppingListItems after deletion."""
    for item_id in getattr(instance, "_cleanup_attr_item_ids", []):
        item = ShoppingListItem.objects.filter(id=item_id).first()
        if item:
            item.recalculate_from_attributions()

    legacy_item_ids = getattr(instance, "_cleanup_legacy_item_ids", [])
    if legacy_item_ids and clear_fields:
        ShoppingListItem.objects.filter(
            id__in=legacy_item_ids,
            attributions__isnull=True,
        ).update(**clear_fields)


@receiver(pre_delete, sender=Recipe)
def capture_items_before_recipe_delete(sender: Any, instance: Recipe, **kwargs: Any) -> None:
    """Record shopping list items linked to a recipe before deletion."""
    _capture_affected_items(
        instance,
        {"recipe": instance},
        {"source_recipe": instance},
    )


@receiver(post_delete, sender=Recipe)
def reconcile_items_after_recipe_delete(sender: Any, instance: Recipe, **kwargs: Any) -> None:
    """Recalculate or unlink shopping list items after a recipe is deleted."""
    _reconcile_affected_items(
        instance,
        {"source_recipe": None, "source_meal": None, "source_ingredient": None},
    )


@receiver(pre_delete, sender=Meal)
def capture_items_before_meal_delete(sender: Any, instance: Meal, **kwargs: Any) -> None:
    """Record shopping list items linked to a meal before deletion."""
    _capture_affected_items(
        instance,
        {"meal": instance},
        {"source_meal": instance},
    )


@receiver(post_delete, sender=Meal)
def reconcile_items_after_meal_delete(sender: Any, instance: Meal, **kwargs: Any) -> None:
    """Recalculate or unlink shopping list items after a meal is deleted."""
    _reconcile_affected_items(
        instance,
        {"source_meal": None, "source_recipe": None, "source_ingredient": None},
    )


@receiver(pre_delete, sender=ShoppingList)
def capture_items_before_preset_delete(sender: Any, instance: ShoppingList, **kwargs: Any) -> None:
    """Record shopping list items linked to a preset list before deletion."""
    if not instance.is_preset:
        return
    _capture_affected_items(
        instance,
        {"preset_list": instance},
        {"source_preset": instance},
    )


@receiver(post_delete, sender=ShoppingList)
def reconcile_items_after_preset_delete(sender: Any, instance: ShoppingList, **kwargs: Any) -> None:
    """Recalculate or unlink shopping list items after a preset list is deleted."""
    if not instance.is_preset:
        return
    _reconcile_affected_items(instance, {"source_preset": None})
