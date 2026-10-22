"""
WebSocket consumers for shopping list real-time synchronization.

Broadcasts changes across multiple connected users instantly using Django Channels.
"""

from typing import Any

from channels.generic.websocket import AsyncWebsocketConsumer


class ShoppingListConsumer(AsyncWebsocketConsumer):
    """
    Consumer handling real-time synchronization of shopping list changes across multiple clients.

    Maintains group subscriptions for shopping lists and pushes out-of-band toasts
    and refresh triggers to keep all users in sync without full page reloads.
    """

    group_name: str
    list_id: int | str | None

    async def connect(self) -> None:
        """Join the shopping list group and accept the WebSocket connection."""
        url_route = self.scope.get("url_route", {})
        kwargs = url_route.get("kwargs", {}) if url_route else {}
        self.list_id = kwargs.get("list_id")
        self.group_name = (
            f"shopping_list_{self.list_id}" if self.list_id else "shopping_list_main"
        )

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code: int) -> None:
        """Leave the shopping list group upon client disconnection."""
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def shopping_update(self, event: dict[str, Any]) -> None:
        """
        Handle a broadcasted shopping list update.

        Pushes an out-of-band toast notification and a trigger to refresh the list
        for all connected users except the sender who already received an immediate HTTP response.

        Args:
            event: Event dictionary containing toast_message, actor_name, and sender_client_id.
        """
        toast_message = event.get("toast_message", "")
        sender_client_id = event.get("sender_client_id", "")

        # Format toast HTML if a message was provided
        toast_html = ""
        if toast_message:
            toast_html = (
                f'<div id="toast-container" hx-swap-oob="beforeend">'
                f'<div class="toast-item pointer-events-auto flex items-center justify-between '
                f'bg-white/90 backdrop-blur-sm text-gray-900 text-xs px-3.5 py-2.5 shadow-lg '
                f'border border-gray-300 min-w-[260px] max-w-sm rounded-none">'
                f'<span class="font-medium pr-2">{toast_message}</span>'
                f'<button type="button" onclick="dismissToast(this.closest(\'.toast-item\'))" '
                f'class="text-gray-400 hover:text-gray-800 font-bold text-base ml-2 leading-none focus:outline-none">&times;</button>'
                f'</div></div>'
            )

        # Trigger refresh on body for all clients except the one that initiated the change
        trigger_script = (
            f'<div id="ws-event-trigger" hx-swap-oob="outerHTML">'
            f'<script>'
            f'if (!window.CLIENT_ID || window.CLIENT_ID !== "{sender_client_id}") {{'
            f'    document.body.dispatchEvent(new CustomEvent("refresh-shopping-list"));'
            f'}}'
            f'</script>'
            f'</div>'
        )

        message_html = f"{toast_html}\n{trigger_script}"
        await self.send(text_data=message_html)
