"""Data migration backfilling baseline ShoppingListItemHistory logs for existing items."""

from django.db import migrations


def _fmt_qty(amount, unit):
    """Format Decimal amount + unit cleanly inside migration without external imports."""
    raw = f"{amount.normalize():f}"
    num_str = raw.rstrip("0").rstrip(".") if "." in raw else raw
    u = (unit or "").strip()
    return f"{num_str} {u}".strip() if u else num_str


def _actor_label(user, fallback_name=""):
    """Resolve human-readable actor label from User model."""
    if user:
        first_name = (getattr(user, "first_name", "") or "").strip()
        return first_name or user.username
    raw = (fallback_name or "").strip()
    if raw and raw.lower() != "unknown":
        return raw
    return raw or "System"


def backfill_shopping_item_history(apps, schema_editor):
    """Populate initial history rows for pre-existing ShoppingListItem entries."""
    ShoppingListItem = apps.get_model("shopping", "ShoppingListItem")
    ShoppingListItemHistory = apps.get_model("shopping", "ShoppingListItemHistory")

    status_labels = {
        "NEED": "Need",
        "GOT": "Got",
        "HAVE": "Already Have",
        "DONT_NEED": "Don't Actually Need",
    }

    existing_logged_ids = set(
        ShoppingListItemHistory.objects.values_list("item_id", flat=True).distinct()
    )
    items = (
        ShoppingListItem.objects.exclude(id__in=existing_logged_ids)
        .select_related(
            "shopping_list",
            "shopping_list__owner",
            "source_recipe",
            "source_meal",
            "source_preset",
            "status_changed_by",
        )
        .prefetch_related(
            "attributions",
            "attributions__recipe",
            "attributions__meal",
            "attributions__preset_list",
        )
    )

    to_create = []
    for item in items:
        owner = item.shopping_list.owner if item.shopping_list else None
        initial_actor = item.status_changed_by or owner
        initial_actor_name = _actor_label(
            initial_actor,
            item.status_changed_by_name if initial_actor == item.status_changed_by else "",
        )

        attrs = list(item.attributions.all())
        if attrs:
            for idx, attr in enumerate(attrs):
                qty_txt = _fmt_qty(attr.amount, attr.amount_unit)
                if attr.recipe:
                    summary = f"Added {qty_txt} from recipe '{attr.recipe.name}'"
                    if attr.meal:
                        summary += f" (Meal: '{attr.meal.name}')"
                elif attr.preset_list:
                    summary = f"Loaded {qty_txt} from preset list '{attr.preset_list.name}'"
                elif attr.meal:
                    summary = f"Added {qty_txt} for meal '{attr.meal.name}'"
                else:
                    summary = f"Added {qty_txt} ({attr.purpose or 'one-time purchase'})"

                preset_origin = attr.preset_list if (attr.preset_list and attr.preset_list.is_preset) else None
                to_create.append(
                    ShoppingListItemHistory(
                        item=item,
                        action="created" if idx == 0 else "added_source",
                        summary=summary,
                        actor=initial_actor,
                        actor_name=initial_actor_name[:150],
                        related_recipe=attr.recipe,
                        related_meal=attr.meal,
                        related_list=preset_origin,
                        created_at=attr.created_at or item.created_at,
                    )
                )
        else:
            qty_txt = _fmt_qty(item.amount, item.amount_unit)
            if item.source_recipe:
                summary = f"Added {qty_txt} from recipe '{item.source_recipe.name}'"
            elif item.source_preset:
                summary = f"Loaded {qty_txt} from preset list '{item.source_preset.name}'"
            elif item.source_meal:
                summary = f"Added {qty_txt} for meal '{item.source_meal.name}'"
            else:
                purpose = (item.purpose or "").strip()
                summary = f"Added {qty_txt}" + (f" ({purpose})" if purpose else "")

            preset_origin = item.source_preset if (item.source_preset and item.source_preset.is_preset) else None
            to_create.append(
                ShoppingListItemHistory(
                    item=item,
                    action="created",
                    summary=summary,
                    actor=initial_actor,
                    actor_name=initial_actor_name[:150],
                    related_recipe=item.source_recipe,
                    related_meal=item.source_meal,
                    related_list=preset_origin,
                    created_at=item.created_at,
                )
            )

        if item.status != "NEED" or (
            item.status_changed_at
            and item.created_at
            and (item.status_changed_at - item.created_at).total_seconds() > 2
        ):
            st_label = status_labels.get(item.status, item.status)
            st_actor = item.status_changed_by
            st_actor_name = _actor_label(st_actor, item.status_changed_by_name)
            to_create.append(
                ShoppingListItemHistory(
                    item=item,
                    action="status_changed",
                    summary=f"Status set to {st_label}",
                    actor=st_actor,
                    actor_name=st_actor_name[:150],
                    created_at=item.status_changed_at or item.updated_at or item.created_at,
                )
            )

    if to_create:
        ShoppingListItemHistory.objects.bulk_create(to_create, batch_size=500)


def noop_reverse(apps, schema_editor):
    """Reverse no-op for initial history backfill."""


class Migration(migrations.Migration):

    dependencies = [
        ("shopping", "0019_shoppinglistitemhistory"),
    ]

    operations = [
        migrations.RunPython(backfill_shopping_item_history, noop_reverse),
    ]
