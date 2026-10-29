"""
Cleanup service for expired completed shopping list items.

Handles automated purging of standalone items in 'Got' and 'Already Have' sections
that have remained past the workspace's configured retention threshold.
Preserves items associated with recipes or preset list templates.
"""

import datetime
import logging
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from apps.core.models import Workspace

logger = logging.getLogger(__name__)


def purge_expired_completed_items(workspace: "Workspace | None") -> int:
    """
    Remove items from a workspace's active shopping list that:
    - Are in 'Got' (ItemStatus.GOT) or 'Already Have' (ItemStatus.HAVE) status.
    - Are NOT associated with recipes (source_recipe, source_meal, source_ingredient are null).
    - Are NOT associated with preset lists (source_preset is null).
    - Have been in their current section/status longer than the workspace's configured retention period.

    If retention is disabled (0 or None), no items are removed.

    Args:
        workspace: Target Workspace instance.

    Returns:
        Number of items deleted.
    """
    if not workspace:
        return 0

    retention_days = workspace.completed_items_retention_days
    if retention_days is None or retention_days <= 0:
        return 0

    from apps.shopping.models import ItemStatus, ShoppingListItem

    cutoff = timezone.now() - datetime.timedelta(days=retention_days)

    qs = ShoppingListItem.objects.filter(
        shopping_list__workspace=workspace,
        shopping_list__is_preset=False,
        status__in=[ItemStatus.GOT, ItemStatus.HAVE],
        source_recipe__isnull=True,
        source_meal__isnull=True,
        source_ingredient__isnull=True,
        source_preset__isnull=True,
    ).filter(
        models.Q(status_changed_at__lte=cutoff)
        | models.Q(status_changed_at__isnull=True, updated_at__lte=cutoff)
    )

    count, _ = qs.delete()
    if count > 0:
        logger.info(
            "Purged %d expired completed items from workspace '%s' (retention: %d days)",
            count,
            workspace.name,
            retention_days,
        )
    return count


def purge_all_expired_completed_items() -> int:
    """
    Purge expired completed items across all workspaces with active retention enabled (>0).

    Returns:
        Total number of items deleted across all workspaces.
    """
    from apps.core.models import Workspace
    from apps.shopping.services.broadcaster import broadcast_shopping_list_update

    total_deleted = 0
    active_workspaces = Workspace.objects.filter(completed_items_retention_days__gt=0)
    for ws in active_workspaces:
        try:
            deleted = purge_expired_completed_items(ws)
            if deleted > 0:
                total_deleted += deleted
                primary_list = ws.get_primary_list()
                if primary_list:
                    broadcast_shopping_list_update(
                        shopping_list=primary_list,
                        toast_message=None,
                    )
        except Exception as exc:
            logger.exception("Failed to purge expired items for workspace '%s': %s", ws.name, exc)

    return total_deleted
