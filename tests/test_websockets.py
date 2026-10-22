"""
Tests for real-time WebSocket synchronization across multiple users.
"""

from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.urls import reverse

from apps.shopping.consumers import ShoppingListConsumer
from apps.shopping.models import ItemStatus, ShoppingList, ShoppingListItem
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from config.asgi import application


@pytest.fixture
def websocket_shopping_list(db):
    """Fixture providing a shopping list for WebSocket tests."""
    from django.contrib.auth import get_user_model

    from apps.core.models import Workspace
    User = get_user_model()
    owner, _ = User.objects.get_or_create(username="ws_test_user")
    ws, _ = Workspace.objects.get_or_create(name="WS Live Sync", defaults={"owner": owner})
    s_list = ShoppingList.objects.create(
        name="Live Sync List",
        is_preset=False,
        workspace=ws,
        owner=owner,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Oranges",
        amount=Decimal("3.00"),
        status=ItemStatus.NEED,
        order=1,
    )
    return s_list


def test_websocket_connection_and_broadcast(websocket_shopping_list):
    """Test WebSocket connection establishment and broadcast delivery."""
    async def run_test():
        communicator = WebsocketCommunicator(ShoppingListConsumer.as_asgi(), "/ws/shopping/")
        connected, _ = await communicator.connect()
        assert connected

        # Broadcast an update to the shopping list
        broadcast_shopping_list_update(
            shopping_list=websocket_shopping_list,
            toast_message="🛒 Alice moved 'Oranges' to Cart",
            actor_name="Alice",
            sender_client_id="client_sender_123",
        )

        # Receive the message over the WebSocket
        response = await communicator.receive_json_from()
        assert response["type"] == "shopping_update"
        assert "Alice moved" in response["toast_message"]
        assert "Oranges" in response["toast_message"]
        assert response["actor_name"] == "Alice"
        assert response["sender_client_id"] == "client_sender_123"

        # Disconnect cleanly
        await communicator.disconnect()

    async_to_sync(run_test)()


def test_websocket_via_asgi_application(websocket_shopping_list):
    """Test connecting to the full ASGI application route."""
    async def run_test():
        communicator = WebsocketCommunicator(application, "/ws/shopping/")
        connected, _ = await communicator.connect()
        assert connected

        broadcast_shopping_list_update(
            shopping_list=websocket_shopping_list,
            toast_message="Bob added 'Bread'",
            actor_name="Bob",
        )

        response = await communicator.receive_json_from()
        assert response["type"] == "shopping_update"
        assert "Bob added" in response["toast_message"]
        assert response["actor_name"] == "Bob"

        await communicator.disconnect()

    async_to_sync(run_test)()


@pytest.mark.django_db(transaction=True)
def test_item_mutation_triggers_websocket_broadcast(client, websocket_shopping_list):
    """Test that performing a list action via HTTP triggers a WebSocket broadcast."""
    from asgiref.sync import sync_to_async

    client.force_login(websocket_shopping_list.owner)
    item_id = websocket_shopping_list.items.first().id

    async def run_test():
        communicator = WebsocketCommunicator(ShoppingListConsumer.as_asgi(), "/ws/shopping/")
        connected, _ = await communicator.connect()
        assert connected

        # Perform an item status change via HTTP POST using sync_to_async
        post_fn = sync_to_async(client.post)
        response = await post_fn(
            reverse("shopping:set_status", args=[item_id, "GOT"]),
            HTTP_X_CLIENT_ID="sender_browser_tab",
        )
        assert response.status_code == 200

        # Verify that the WebSocket consumer received the broadcast
        ws_msg = await communicator.receive_json_from()
        assert ws_msg["type"] == "shopping_update"
        assert "Oranges" in ws_msg["toast_message"]
        assert ws_msg["sender_client_id"] == "sender_browser_tab"

        await communicator.disconnect()

    async_to_sync(run_test)()
