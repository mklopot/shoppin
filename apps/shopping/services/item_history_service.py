"""
Audit trail service for recording and summarizing ShoppingListItem history.

Captures user-attributed actions (creation, field edits, merges, status changes,
Pantry Check locks, priority flags, recipe/meal scaling, deductions, and preset runs)
plus current recipe, meal, and list associations for the item Edit dialog.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from apps.core.utils import clean_purpose, format_amount, pluralize_unit, singularize_unit
from apps.shopping.models import (
    ItemHistoryAction,
    ItemStatus,
    ShoppingList,
    ShoppingListItem,
    ShoppingListItemHistory,
)


@dataclass
class FallbackHistoryEntry:
    """Synthetic history row for legacy/ORM-created items with no persisted log rows yet."""

    action: str
    action_label: str
    summary: str
    actor_display: str
    created_at: Any
    related_recipe: Any = None
    related_meal: Any = None
    related_list: Any = None

    def get_action_display(self) -> str:
        """Return display label matching ShoppingListItemHistory.get_action_display()."""
        return self.action_label


def format_quantity_text(amount: Decimal, unit: str) -> str:
    """Format '<amount> <unit>' cleanly with singular/plural unit inflection."""
    amt_str = format_amount(amount)
    u = (unit or "").strip()
    if not u:
        return amt_str
    u_disp = singularize_unit(u) if amount == Decimal("1.00") or amount == 1 else pluralize_unit(u)
    return f"{amt_str} {u_disp}".strip()


def resolve_actor_from_request(
    request: HttpRequest | None = None,
    user: Any = None,
    default_name: str = "System",
) -> tuple[Any | None, str]:
    """Resolve authenticated User instance and display name from request/user."""
    target_user = user
    if target_user is None and request is not None:
        req_user = getattr(request, "user", None)
        if req_user and getattr(req_user, "is_authenticated", False):
            target_user = req_user

    if target_user and getattr(target_user, "is_authenticated", False):
        first_name = (getattr(target_user, "first_name", "") or "").strip()
        return target_user, (first_name or target_user.username)

    if request is not None:
        header_name = (request.headers.get("X-Client-Name") or "").strip()
        if header_name and header_name.lower() not in ("you", "unknown"):
            return None, header_name.split()[0]
        return None, "Unknown"

    return None, default_name


def log_item_history(
    item: ShoppingListItem | None,
    action: str,
    summary: str,
    *,
    request: HttpRequest | None = None,
    user: Any = None,
    actor_name: str = "",
    related_recipe: Any = None,
    related_meal: Any = None,
    related_list: Any = None,
    created_at: Any = None,
) -> ShoppingListItemHistory | None:
    """Persist a single immutable ShoppingListItemHistory record."""
    if not item or not getattr(item, "pk", None):
        return None

    actor_user, resolved_name = resolve_actor_from_request(
        request=request,
        user=user,
        default_name=actor_name or "System",
    )
    final_actor_name = actor_name.strip() if actor_name.strip() else resolved_name

    return ShoppingListItemHistory.objects.create(
        item=item,
        action=action,
        summary=summary,
        actor=actor_user,
        actor_name=final_actor_name[:150],
        related_recipe=related_recipe,
        related_meal=related_meal,
        related_list=related_list,
        created_at=created_at or timezone.now(),
    )


def snapshot_item_fields(item: ShoppingListItem) -> dict[str, Any]:
    """Capture editable item fields prior to update so diffs can be logged concisely."""
    return {
        "name": (item.name or "").strip(),
        "quantity": format_quantity_text(item.amount, item.amount_unit),
        "category": (item.category or "").strip(),
        "aisle": (item.aisle or "").strip(),
        "brand": (item.brand or "").strip(),
        "vendor": (item.vendor or "").strip(),
        "purpose": clean_purpose(item.purpose) or "",
        "priority": bool(item.priority),
        "locked": bool(item.locked),
        "optional": bool(item.optional),
        "is_active": bool(item.is_active),
    }


def format_item_diff_summary(before: dict[str, Any], after_item: ShoppingListItem) -> str | None:
    """Build a human-readable summary of field changes between before snapshot and saved item."""
    after = snapshot_item_fields(after_item)
    changes: list[str] = []

    str_fields = (
        ("name", "name"),
        ("quantity", "amount"),
        ("category", "category"),
        ("aisle", "aisle"),
        ("brand", "brand"),
        ("vendor", "vendor"),
        ("purpose", "purpose"),
    )
    for key, label in str_fields:
        old_val = before.get(key, "")
        new_val = after.get(key, "")
        if old_val != new_val:
            changes.append(f"{label} '{old_val or 'blank'}' \u2192 '{new_val or 'blank'}'")

    bool_fields = (
        ("priority", "priority"),
        ("locked", "pantry lock"),
        ("optional", "optional"),
        ("is_active", "active on schedule"),
    )
    for key, label in bool_fields:
        if before.get(key) != after.get(key):
            old_lbl = "Yes" if before.get(key) else "No"
            new_lbl = "Yes" if after.get(key) else "No"
            changes.append(f"{label} {old_lbl} \u2192 {new_lbl}")

    if not changes:
        return None
    return "Updated " + ", ".join(changes)


def transfer_item_history(source_item: ShoppingListItem, target_item: ShoppingListItem) -> None:
    """Preserve all prior history logs when source_item is merged into target_item."""
    if not source_item.pk or not target_item.pk or source_item.pk == target_item.pk:
        return
    ShoppingListItemHistory.objects.filter(item=source_item).update(item=target_item)


def _synthesize_fallback_history(item: ShoppingListItem) -> list[FallbackHistoryEntry]:
    """Generate baseline history entries for items lacking stored ShoppingListItemHistory rows."""
    entries: list[FallbackHistoryEntry] = []
    status_label = ItemStatus(item.status).label if item.status in ItemStatus.values else item.status
    initial_actor = item.status_actor_first_name or (
        ((item.shopping_list.owner.first_name or "").strip() or item.shopping_list.owner.username)
        if (item.shopping_list and item.shopping_list.owner)
        else "System"
    )

    attributions = list(
        item.attributions.select_related("recipe", "meal", "preset_list").all()
    )
    if attributions:
        for attr in attributions:
            qty_txt = format_quantity_text(attr.amount, attr.amount_unit)
            if attr.recipe:
                summary = f"Added {qty_txt} from recipe '{attr.recipe.name}'"
                if attr.meal:
                    summary += f" (Meal: '{attr.meal.name}')"
            elif attr.preset_list:
                summary = f"Loaded {qty_txt} from preset list '{attr.preset_list.name}'"
            elif attr.meal:
                summary = f"Added {qty_txt} for meal '{attr.meal.name}'"
            else:
                summary = f"Added {qty_txt} ({clean_purpose(attr.purpose) or 'one-time purchase'})"

            entries.append(
                FallbackHistoryEntry(
                    action=ItemHistoryAction.CREATED,
                    action_label=ItemHistoryAction.CREATED.label,
                    summary=summary,
                    actor_display=initial_actor,
                    created_at=attr.created_at or item.created_at,
                    related_recipe=attr.recipe,
                    related_meal=attr.meal,
                    related_list=attr.preset_list if (attr.preset_list and attr.preset_list.is_preset) else None,
                )
            )
    else:
        qty_txt = format_quantity_text(item.amount, item.amount_unit)
        purpose_txt = clean_purpose(item.purpose)
        if item.source_recipe:
            summary = f"Added {qty_txt} from recipe '{item.source_recipe.name}'"
        elif item.source_preset:
            summary = f"Loaded {qty_txt} from preset list '{item.source_preset.name}'"
        elif item.source_meal:
            summary = f"Added {qty_txt} for meal '{item.source_meal.name}'"
        else:
            summary = f"Added {qty_txt}" + (f" ({purpose_txt})" if purpose_txt else "")
        entries.append(
            FallbackHistoryEntry(
                action=ItemHistoryAction.CREATED,
                action_label=ItemHistoryAction.CREATED.label,
                summary=summary,
                actor_display=initial_actor,
                created_at=item.created_at,
                related_recipe=item.source_recipe,
                related_meal=item.source_meal,
                related_list=item.source_preset if (item.source_preset and item.source_preset.is_preset) else None,
            )
        )

    if item.status != ItemStatus.NEED or (
        item.status_changed_at
        and item.created_at
        and (item.status_changed_at - item.created_at).total_seconds() > 2
    ):
        entries.append(
            FallbackHistoryEntry(
                action=ItemHistoryAction.STATUS_CHANGED,
                action_label=ItemHistoryAction.STATUS_CHANGED.label,
                summary=f"Current status: {status_label}",
                actor_display=item.status_actor_first_name or "Unknown",
                created_at=item.status_changed_at or item.updated_at or item.created_at,
            )
        )

    entries.sort(key=lambda e: e.created_at or timezone.now(), reverse=True)
    return entries


def get_item_associations_and_history(item: ShoppingListItem) -> dict[str, Any]:
    """
    Collect actual originating recipe and preset-list associations plus chronological history
    for rendering the collapsed 'Advanced' section inside the item Edit dialog.
    """
    seen_recipes: dict[int, Any] = {}
    seen_lists: dict[int, ShoppingList] = {}

    for attr in item.attributions.select_related("recipe", "preset_list").all():
        if attr.recipe_id and attr.recipe:
            seen_recipes[attr.recipe.id] = attr.recipe
        if attr.preset_list_id and attr.preset_list and attr.preset_list.is_preset:
            seen_lists[attr.preset_list.id] = attr.preset_list

    if item.source_recipe_id and item.source_recipe:
        seen_recipes[item.source_recipe.id] = item.source_recipe
    if item.source_preset_id and item.source_preset and item.source_preset.is_preset:
        seen_lists[item.source_preset.id] = item.source_preset

    history_entries: list[Any] = list(
        item.history_logs.select_related(
            "actor",
            "related_recipe",
            "related_meal",
            "related_list",
        ).all()
    )
    if not history_entries:
        history_entries = _synthesize_fallback_history(item)

    ordered_lists = sorted(seen_lists.values(), key=lambda lst: lst.name.lower())

    return {
        "associated_recipes": list(seen_recipes.values()),
        "associated_lists": ordered_lists,
        "history_entries": history_entries,
    }


def log_signal_source_deletion(item: ShoppingListItem, origin_desc: str) -> None:
    """Record when deleting an external Recipe/Meal/Preset reduced a surviving item."""
    if not item or not item.pk:
        return
    qty_txt = format_quantity_text(item.amount, item.amount_unit)
    log_item_history(
        item,
        ItemHistoryAction.DEDUCTED,
        f"Recalculated after {origin_desc} was removed \u2192 remaining {qty_txt}",
    )


__all__ = [
    "format_item_diff_summary",
    "format_quantity_text",
    "get_item_associations_and_history",
    "log_item_history",
    "log_signal_source_deletion",
    "resolve_actor_from_request",
    "snapshot_item_fields",
    "transfer_item_history",
]
