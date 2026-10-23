"""
WebSocket consumers for shopping list real-time synchronization.

Broadcasts changes across multiple connected users instantly using Django Channels.
"""

from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class ShoppingListConsumer(AsyncJsonWebsocketConsumer):
    """
    Consumer handling real-time synchronization of shopping list changes across multiple clients.

    Subscribes connected tabs to the shopping list channel group and delivers JSON events.
    """

    group_name: str
    list_id: int | str | None

    async def connect(self) -> None:
        """Join the shopping list group and accept the WebSocket connection."""
        url_route = self.scope.get("url_route", {})
        kwargs = url_route.get("kwargs", {}) if url_route else {}
        self.list_id = kwargs.get("list_id")

        # Always join shopping_list_main so all connected tabs receive real-time updates and toasts
        await self.channel_layer.group_add("shopping_list_main", self.channel_name)
        if self.list_id:
            await self.channel_layer.group_add(f"shopping_list_{self.list_id}", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Leave the shopping list group upon client disconnection."""
        await self.channel_layer.group_discard("shopping_list_main", self.channel_name)
        if self.list_id:
            await self.channel_layer.group_discard(f"shopping_list_{self.list_id}", self.channel_name)

    async def shopping_update(self, event: dict[str, Any]) -> None:
        """
        Deliver JSON shopping update event to the connected WebSocket client.

        Args:
            event: Event dictionary containing toast_message, actor_name, and sender_client_id.
        """
        await self.send_json({
            "type": "shopping_update",
            "toast_message": event.get("toast_message", ""),
            "toast_messages": event.get("toast_messages", []),
            "actor_name": event.get("actor_name", "unknown"),
            "sender_client_id": event.get("sender_client_id", ""),
        })
