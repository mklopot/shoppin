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


def test_workspace_dropdown_shows_extended_width_and_title(client, workspace_setup, workspace_users):
    """Test that the workspace pulldown renders with extended max-width and tooltip title."""
    ws = workspace_setup["workspace"]
    ws.name = "My Very Long And Elaborate Kitchen Workspace 2026"
    ws.save()

    client.force_login(workspace_users["owner"])
    response = client.get(reverse("shopping:list"))
    assert response.status_code == 200

    content = response.content.decode()
    # Verify the dropdown button has the full name as a title tooltip
    assert f'title="{ws.name}"' in content
    # Verify the dropdown button text container uses widened max-width classes
    assert "max-w-[190px]" in content or "max-w-[240px]" in content or "max-w-[110px]" in content
    # Verify the dropdown menu uses widened container
    assert "w-64" in content or "w-72" in content


def test_update_workspace_name_oob_updates_dropdown(client, workspace_setup, workspace_users):
    """Test that updating the workspace name immediately re-renders the navbar dropdown out-of-band."""
    ws = workspace_setup["workspace"]
    owner = workspace_users["owner"]
    client.force_login(owner)

    new_name = "Sunny Meadows Homestead"
    update_url = reverse("core:update_workspace_settings", args=[ws.id])
    response = client.post(
        update_url,
        {"name": new_name, "completed_items_retention_days": "7"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200

    ws.refresh_from_db()
    assert ws.name == new_name

    content = response.content.decode()
    # Verify out-of-band swap updates the navbar dropdown immediately without reload
    assert 'id="workspace-dropdown-container"' in content
    assert 'hx-swap-oob="outerHTML"' in content
    assert new_name in content
    # Verify client-side script update is present
    assert f'"{new_name}"' in content


def test_clear_workspace_removes_items_unloads_presets_clears_mealplan(client, workspace_setup, workspace_users):
    """
    Test clearing workspace: removes all shopping list items,
    unloads all presets from shopping list, and clears all meals from the meal plan,
    while preserving preset list templates and recipes.
    """
    from apps.core.services.workspace_service import clear_workspace_data
    from apps.mealplans.models import Meal, MealDish, MealPlan
    from apps.recipes.models import Ingredient, Recipe
    from apps.shopping.models import ShoppingListItemSource
    from apps.shopping.services.preset_service import create_preset_list, add_preset_item, load_preset_items_to_shopping_list

    ws = workspace_setup["workspace"]
    owner = workspace_users["owner"]
    primary_list = workspace_setup["shopping_list"]

    # 1. Add recipe and meal with dish to meal plan
    meal_plan = ws.get_meal_plan()
    recipe = Recipe.objects.create(name="Chicken Quesadillas", created_by=owner)
    Ingredient.objects.create(recipe=recipe, name="Tortillas", amount=Decimal("4.00"), amount_unit="pieces")
    Ingredient.objects.create(recipe=recipe, name="Cheddar Cheese", amount=Decimal("200.00"), amount_unit="g")

    meal = Meal.objects.create(meal_plan=meal_plan, name="Friday Dinner")
    dish = MealDish.objects.create(meal=meal, recipe=recipe, scale_factor=Decimal("1.00"))
    # Add dish ingredient to shopping list
    item_ques = primary_list.items.create(name="Tortillas", amount=Decimal("4.00"), purpose="Dish: Chicken Quesadillas")
    ShoppingListItemSource.objects.create(item=item_ques, meal=meal, meal_dish=dish, recipe=recipe, amount=Decimal("4.00"))

    # 2. Add preset list and load it to shopping list
    preset = create_preset_list(workspace=ws, name="Baking Supplies")
    add_preset_item(preset, name="Vanilla Extract", amount=Decimal("1.00"))
    add_preset_item(preset, name="Baking Powder", amount=Decimal("1.00"))
    load_preset_items_to_shopping_list(preset, primary_list)

    # 3. Add manual standalone item
    primary_list.items.create(name="Sponge", amount=Decimal("1.00"), purpose="One-time purchase")

    # Verify initial populated state
    assert primary_list.items.count() >= 4
    assert meal_plan.meals.count() == 1
    assert ws.shopping_lists.filter(is_preset=True).count() == 1

    # Call clear workspace via HTMX POST
    client.force_login(owner)
    clear_url = reverse("core:clear_workspace", args=[ws.id])
    response = client.post(clear_url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200

    content = response.content.decode()
    assert "Workspace cleared successfully" in content

    # Verify state after clearing:
    # 1. Shopping list items are all cleared
    assert primary_list.items.count() == 0
    # 2. Meal plan meals are cleared out
    assert meal_plan.meals.count() == 0
    # 3. Preset template STILL exists
    assert ws.shopping_lists.filter(is_preset=True, name="Baking Supplies").exists()
    preset.refresh_from_db()
    assert preset.items.count() == 2
    # 4. Recipe STILL exists
    assert Recipe.objects.filter(id=recipe.id).exists()


def test_clear_workspace_permission_denied_for_non_owner(client, workspace_setup, workspace_users):
    """Test that editors and viewers cannot clear workspace data."""
    ws = workspace_setup["workspace"]
    editor = workspace_users["editor"]
    viewer = workspace_users["viewer"]
    primary_list = workspace_setup["shopping_list"]

    clear_url = reverse("core:clear_workspace", args=[ws.id])

    # Editor attempts clear
    client.force_login(editor)
    resp_editor = client.post(clear_url, HTTP_HX_REQUEST="true")
    assert resp_editor.status_code == 403
    assert primary_list.items.count() > 0

    # Viewer attempts clear
    client.force_login(viewer)
    resp_viewer = client.post(clear_url, HTTP_HX_REQUEST="true")
    assert resp_viewer.status_code == 403
    assert primary_list.items.count() > 0


def test_clear_workspace_modal_contains_confirmation(client, workspace_setup, workspace_users):
    """Test that the workspace settings modal includes the clear button and confirmation prompt."""
    ws = workspace_setup["workspace"]
    owner = workspace_users["owner"]
    client.force_login(owner)

    modal_url = reverse("core:workspace_settings", args=[ws.id])
    response = client.get(modal_url)
    assert response.status_code == 200

    content = response.content.decode()
    assert "Clear Workspace" in content
    assert "hx-confirm=" in content
    assert "Remove all items now on the shopping list" in content
    assert reverse("core:clear_workspace", args=[ws.id]) in content
