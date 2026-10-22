"""
Broadcasting service for real-time WebSocket updates via Django Channels.
"""

import asyncio
import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.shopping.models import ShoppingList

logger = logging.getLogger(__name__)


def broadcast_shopping_list_update(
    shopping_list: ShoppingList | None = None,
    toast_message: str | None = None,
    actor_name: str | None = None,
    sender_client_id: str | None = None,
) -> None:
    """
    Broadcast a real-time update notification to all clients viewing the shopping list.

    Safely dispatches from both synchronous Django view threads and active async event loops.

    Args:
        shopping_list: Optional ShoppingList instance.
        toast_message: Optional user-facing notification string.
        actor_name: Name of the user who performed the action.
        sender_client_id: Optional client ID header to prevent redundant re-fetching by the sender.
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        payload: dict[str, Any] = {
            "type": "shopping_update",
            "toast_message": toast_message or "",
            "actor_name": actor_name or "unknown",
            "sender_client_id": sender_client_id or "",
        }

        groups = ["shopping_list_main"]
        if shopping_list and shopping_list.id:
            groups.append(f"shopping_list_{shopping_list.id}")

        # Check if an event loop is already running in current thread
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            for grp in groups:
                asyncio.create_task(channel_layer.group_send(grp, payload))
        else:
            for grp in groups:
                async_to_sync(channel_layer.group_send)(grp, payload)
    except Exception as error:
        logger.warning(f"Could not broadcast shopping list update over WebSockets: {error}")
