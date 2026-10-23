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



@pytest.mark.django_db(transaction=True)
def test_add_dish_in_mealplan_triggers_websocket_broadcast(client, websocket_shopping_list):
    """Test that adding a dish in meal plan triggers real-time WebSocket broadcast to shopping list."""
    from asgiref.sync import sync_to_async

    from apps.mealplans.models import Meal, MealPlan
    from apps.recipes.models import Ingredient, Recipe

    user = websocket_shopping_list.owner
    client.force_login(user)

    ws = websocket_shopping_list.workspace
    meal_plan = MealPlan.objects.create(name="Weekly Plan", workspace=ws)
    meal = Meal.objects.create(meal_plan=meal_plan, name="Taco Night")
    recipe = Recipe.objects.create(name="Carnitas Tacos", directions="Cook pork")
    Ingredient.objects.create(recipe=recipe, name="Pork Shoulder", amount=Decimal("2.00"), amount_unit="lb")

    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    async def run_test():
        communicator = WebsocketCommunicator(
            ShoppingListConsumer.as_asgi(),
            f"/ws/shopping/{websocket_shopping_list.id}/",
        )
        connected, _ = await communicator.connect()
        assert connected

        post_fn = sync_to_async(client.post)
        response = await post_fn(
            reverse("mealplans:add_dish", args=[meal.id]),
            {"recipe_id": recipe.id},
            HTTP_X_CLIENT_ID="mealplan_browser_tab",
        )
        assert response.status_code == 200

        ws_msg = await communicator.receive_json_from()
        assert ws_msg["type"] == "shopping_update"
        assert "Carnitas Tacos" in ws_msg["toast_message"]
        assert ws_msg["sender_client_id"] == "mealplan_browser_tab"
        assert "toast_messages" in ws_msg
        assert any("Pork Shoulder" in m for m in ws_msg["toast_messages"])

        await communicator.disconnect()

    async_to_sync(run_test)()


@pytest.mark.django_db(transaction=True)
def test_preset_schedule_triggers_websocket_broadcast_and_toasts(client, websocket_shopping_list):
    """Test that preset schedule updates and refreshes trigger real-time WebSocket broadcasts and toasts to other tabs."""
    from asgiref.sync import sync_to_async

    from apps.shopping.services.preset_service import add_preset_item, create_preset_list

    user = websocket_shopping_list.owner
    client.force_login(user)

    ws = websocket_shopping_list.workspace
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    preset = create_preset_list(ws, "Breakfast Essentials", interval_days=7, is_schedule_enabled=True)
    item = add_preset_item(preset, "Oat Milk", amount="1", is_active=True)

    async def run_test():
        communicator = WebsocketCommunicator(
            ShoppingListConsumer.as_asgi(),
            "/ws/shopping/",
        )
        connected, _ = await communicator.connect()
        assert connected

        post_fn = sync_to_async(client.post)

        # 1. Update preset schedule in Tab A
        resp1 = await post_fn(
            reverse("shopping:preset_update_schedule", args=[preset.id]),
            {
                "interval_days": "14",
                "is_schedule_enabled": "on",
                "next_occurrence_date": "2026-11-10",
                "next_occurrence_time": "9:00 AM",
            },
            HTTP_HX_REQUEST="true",
            HTTP_X_CLIENT_ID="tab_A",
        )
        assert resp1.status_code == 200

        # Tab B receives the schedule update toast
        msg1 = await communicator.receive_json_from()
        assert msg1["type"] == "shopping_update"
        assert "Schedule enabled for preset 'Breakfast Essentials'" in msg1["toast_message"]
        assert msg1["sender_client_id"] == "tab_A"

        # 2. Run schedule now in Tab A
        resp2 = await post_fn(
            reverse("shopping:preset_run_schedule_now", args=[preset.id]),
            HTTP_HX_REQUEST="true",
            HTTP_X_CLIENT_ID="tab_A",
        )
        assert resp2.status_code == 200

        # Tab B receives the preset refresh toast
        msg2 = await communicator.receive_json_from()
        assert msg2["type"] == "shopping_update"
        assert "Preset refresh: 'Breakfast Essentials'" in msg2["toast_message"]
        assert msg2["sender_client_id"] == "tab_A"

        # 3. Toggle item active/inactive in Tab A
        resp3 = await post_fn(
            reverse("shopping:preset_item_toggle_active", args=[preset.id, item.id]),
            HTTP_HX_REQUEST="true",
            HTTP_X_CLIENT_ID="tab_A",
        )
        assert resp3.status_code == 200

        # Tab B receives the item status change toast
        msg3 = await communicator.receive_json_from()
        assert msg3["type"] == "shopping_update"
        assert "Oat Milk" in msg3["toast_message"]
        assert msg3["sender_client_id"] == "tab_A"

        await communicator.disconnect()

    async_to_sync(run_test)()
