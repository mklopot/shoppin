"""
Unit and integration tests for Workspaces, sharing permissions, and static read-only enforcement.
"""

from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from apps.core.models import Workspace, WorkspaceRole
from apps.core.services.workspace_service import (
    create_workspace,
    share_workspace,
)
from apps.shopping.models import ItemStatus, ShoppingListItem
from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from config.asgi import application

User = get_user_model()


@pytest.fixture
def workspace_users(db):
    """Fixture providing standard test users."""
    owner = User.objects.create_user(username="test_owner", password="password")
    editor = User.objects.create_user(username="test_editor", password="password")
    viewer = User.objects.create_user(username="test_viewer", password="password")
    stranger = User.objects.create_user(username="test_stranger", password="password")
    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "stranger": stranger,
    }


@pytest.fixture
def workspace_setup(workspace_users):
    """Fixture setting up a workspace with owner, editor, and viewer."""
    ws = create_workspace("Test Household", workspace_users["owner"])
    share_workspace(ws, workspace_users["editor"], WorkspaceRole.EDITOR)
    share_workspace(ws, workspace_users["viewer"], WorkspaceRole.VIEWER)

    # Add an item to the primary list
    s_list = ws.get_primary_list()
    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Bananas",
        amount=Decimal("5.00"),
        status=ItemStatus.NEED,
    )
    return {
        "workspace": ws,
        "shopping_list": s_list,
        "item": item,
    }


def test_workspace_creation_provisions_list_and_mealplan(workspace_users):
    """Test that creating a workspace automatically sets up a shopping list and a meal plan."""
    ws = create_workspace("Summer Retreat", workspace_users["owner"])

    primary_list = ws.get_primary_list()
    assert primary_list is not None
    assert primary_list.workspace == ws
    assert primary_list.is_preset is False
    assert "Summer Retreat" in primary_list.name

    meal_plan = ws.get_meal_plan()
    assert meal_plan is not None
    assert meal_plan.workspace == ws
    assert meal_plan.owner == workspace_users["owner"]


def test_create_workspace_view_authenticated(client, workspace_users):
    """Test that an authenticated user can create a workspace via POST."""
    client.force_login(workspace_users["owner"])
    response = client.post(reverse("core:create_workspace"), {"name": "Lakeside Cabin"})
    assert response.status_code == 302
    assert Workspace.objects.filter(name="Lakeside Cabin", owner=workspace_users["owner"]).exists()


@override_settings(DEBUG=False)
def test_create_workspace_view_unauthenticated_in_production(client):
    """Test that unauthenticated requests receive 403 Forbidden in production."""
    response = client.post(reverse("core:create_workspace"), {"name": "Unauthorized WS"})
    assert response.status_code == 403
    assert b"Must be logged in to create a workspace." in response.content


@override_settings(DEBUG=True)
def test_create_workspace_view_unauthenticated_in_debug(client, workspace_users):
    """Test that unauthenticated requests in DEBUG mode auto-resolve a dev user."""
    response = client.post(reverse("core:create_workspace"), {"name": "Dev Auto WS"})
    assert response.status_code == 302
    assert Workspace.objects.filter(name="Dev Auto WS").exists()


def test_workspace_roles_and_permissions(workspace_setup, workspace_users):
    """Test role evaluation and can_write/can_read permissions."""
    ws = workspace_setup["workspace"]
    owner = workspace_users["owner"]
    editor = workspace_users["editor"]
    viewer = workspace_users["viewer"]
    stranger = workspace_users["stranger"]

    # Owner permissions
    assert ws.get_user_role(owner) == "owner"
    assert ws.can_write(owner) is True
    assert ws.can_read(owner) is True

    # Editor permissions
    assert ws.get_user_role(editor) == WorkspaceRole.EDITOR
    assert ws.can_write(editor) is True
    assert ws.can_read(editor) is True

    # Viewer permissions
    assert ws.get_user_role(viewer) == WorkspaceRole.VIEWER
    assert ws.can_write(viewer) is False
    assert ws.can_read(viewer) is True

    # Stranger permissions
    assert ws.get_user_role(stranger) is None
    assert ws.can_write(stranger) is False
    assert ws.can_read(stranger) is False


def test_switch_workspace_view(client, workspace_setup, workspace_users):
    """Test switching active workspace in session and access control."""
    ws = workspace_setup["workspace"]
    viewer = workspace_users["viewer"]
    stranger = workspace_users["stranger"]

    # Allowed user (viewer) switches workspace
    client.force_login(viewer)
    response = client.get(reverse("core:switch_workspace", args=[ws.id]))
    assert response.status_code == 302
    assert client.session.get("active_workspace_id") == ws.id

    # Unauthorized user (stranger) gets 403 Forbidden
    client.force_login(stranger)
    forbidden_resp = client.get(reverse("core:switch_workspace", args=[ws.id]))
    assert forbidden_resp.status_code == 403


def test_manage_members_and_sharing_view(client, workspace_setup, workspace_users):
    """Test sharing workspace and removing members through views."""
    ws = workspace_setup["workspace"]
    owner = workspace_users["owner"]
    stranger = workspace_users["stranger"]
    editor = workspace_users["editor"]

    # Non-owner cannot share
    client.force_login(editor)
    resp = client.post(
        reverse("core:share_workspace", args=[ws.id]),
        {"user_id": stranger.id, "role": "viewer"},
    )
    assert resp.status_code == 403

    # Owner can share
    client.force_login(owner)
    resp = client.post(
        reverse("core:share_workspace", args=[ws.id]),
        {"user_id": stranger.id, "role": "editor"},
    )
    assert resp.status_code == 200
    assert ws.get_user_role(stranger) == WorkspaceRole.EDITOR

    # Owner can remove member
    resp_remove = client.post(
        reverse("core:remove_member", args=[ws.id, stranger.id]),
    )
    assert resp_remove.status_code == 200
    assert ws.get_user_role(stranger) is None


def test_read_only_viewer_cannot_mutate_items(client, workspace_setup, workspace_users):
    """Verify that a user with Viewer role receives HTTP 403 when attempting mutations."""
    ws = workspace_setup["workspace"]
    viewer = workspace_users["viewer"]
    item = workspace_setup["item"]

    client.force_login(viewer)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # 1. Attempt status change
    resp = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert resp.status_code == 403

    # 2. Attempt add item
    resp = client.post(reverse("shopping:add_item"), {"name": "Unauthorized Item"})
    assert resp.status_code == 403

    # 3. Attempt edit item
    resp = client.post(reverse("shopping:edit_item", args=[item.id]), {"name": "Edited Item"})
    assert resp.status_code == 403

    # 4. Attempt delete item
    resp = client.post(reverse("shopping:delete_item", args=[item.id]))
    assert resp.status_code == 403

    # 5. Attempt reorder items
    resp = client.post(reverse("shopping:reorder"), {"item_ids[]": [str(item.id)]})
    assert resp.status_code == 403


def test_editor_can_mutate_items(client, workspace_setup, workspace_users):
    """Verify that a user with Editor role successfully performs mutations."""
    ws = workspace_setup["workspace"]
    editor = workspace_users["editor"]
    item = workspace_setup["item"]

    client.force_login(editor)
    session = client.session
    session["active_workspace_id"] = ws.id
    session.save()

    # Editor moves item to GOT
    resp = client.post(reverse("shopping:set_status", args=[item.id, "GOT"]))
    assert resp.status_code == 200
    item.refresh_from_db()
    assert item.status == ItemStatus.GOT


@override_settings(DEBUG=True)
def test_dev_persona_switcher(client, workspace_users):
    """Verify the development persona switcher endpoint."""
    user = User.objects.create_user(username="test_persona_alice", password="password")
    response = client.get(reverse("core:switch_persona", args=["test_persona_alice"]))
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.id)


@override_settings(DEBUG=False)
def test_dev_persona_switcher_disabled_in_production(client, workspace_users):
    """Verify the persona switcher is disabled and returns 403 when DEBUG=False."""
    User.objects.create_user(username="test_persona_bob", password="password")
    response = client.get(reverse("core:switch_persona", args=["test_persona_bob"]))
    assert response.status_code == 403


def test_websocket_scoping_between_workspaces(workspace_users):
    """Test that WebSockets connected to list A do not receive list B broadcasts."""
    ws_a = create_workspace("Workspace A", workspace_users["owner"])
    ws_b = create_workspace("Workspace B", workspace_users["owner"])

    list_a = ws_a.get_primary_list()
    list_b = ws_b.get_primary_list()

    async def run_test():
        # Connect to Workspace A's WebSocket room
        communicator_a = WebsocketCommunicator(
            application,
            f"/ws/shopping/{list_a.id}/",
        )
        connected, _ = await communicator_a.connect()
        assert connected

        # Broadcast update to Workspace B
        broadcast_shopping_list_update(
            shopping_list=list_b,
            toast_message="Updated Workspace B list",
            actor_name="Owner",
        )

        # Ensure communicator_a receives NOTHING from Workspace B
        received_b = await communicator_a.receive_nothing(timeout=0.2)
        assert received_b is True

        # Broadcast update to Workspace A
        broadcast_shopping_list_update(
            shopping_list=list_a,
            toast_message="Updated Workspace A list",
            actor_name="Owner",
        )

        # Communicator A should receive the Workspace A broadcast
        response = await communicator_a.receive_json_from()
        assert response["type"] == "shopping_update"
        assert "Updated Workspace A" in response["toast_message"]

        await communicator_a.disconnect()

    async_to_sync(run_test)()
