"""
Workspace service for resolving active workspace, managing multi-tenant scoping,
and administering member sharing permissions.
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.http import HttpRequest

from apps.core.models import Workspace, WorkspaceMember, WorkspaceRole
from apps.mealplans.models import MealPlan
from apps.shopping.models import ShoppingList, StoreLocation

User = get_user_model()


def get_active_workspace(request: HttpRequest | None = None) -> Workspace | None:
    """
    Resolve the currently active Workspace for the request.

    Checks explicit query params (?workspace_id=X), session state,
    and falls back to user's first available workspace. If none exist,
    a personal workspace is automatically initialized for authenticated users.

    Args:
        request: Django HttpRequest or None.

    Returns:
        The active Workspace instance or None if unauthenticated.
    """
    user = getattr(request, "user", None)

    # Strictly enforce authentication: anonymous visitors never have an active workspace
    if not user or not user.is_authenticated:
        return None

    # 1. Check explicit parameter in request
    target_id = None
    if request:
        target_id = request.GET.get("workspace_id") or request.POST.get("workspace_id")

    # 2. Check session state
    if not target_id and request and hasattr(request, "session"):
        target_id = request.session.get("active_workspace_id")

    # 3. If target_id provided, verify access
    if target_id:
        try:
            ws = Workspace.objects.get(id=int(target_id))
            if ws.can_read(user):
                if request and hasattr(request, "session"):
                    request.session["active_workspace_id"] = ws.id
                return ws
        except (Workspace.DoesNotExist, ValueError):
            pass

    # 4. Fallback to first owned workspace, then shared workspace
    owned_ws = user.owned_workspaces.first()
    if owned_ws:
        if request and hasattr(request, "session"):
            request.session["active_workspace_id"] = owned_ws.id
        return owned_ws

    membership = user.workspace_memberships.select_related("workspace").first()
    if membership:
        ws = membership.workspace
        if request and hasattr(request, "session"):
            request.session["active_workspace_id"] = ws.id
        return ws

    # 5. User has no workspaces; auto-provision personal workspace
    ws_name = f"{user.username.capitalize()}'s Workspace"
    ws = create_workspace(ws_name, user)
    if request and hasattr(request, "session"):
        request.session["active_workspace_id"] = ws.id
    return ws


def get_user_workspaces(user: Any) -> list[dict[str, Any]]:
    """
    Retrieve all workspaces accessible by the user, formatted for the UI switcher.

    Args:
        user: Django User instance.

    Returns:
        List of dictionaries with workspace metadata and user role.
    """
    if not user or not user.is_authenticated:
        return []

    results = []

    # Owned workspaces
    for ws in user.owned_workspaces.all().order_by("name"):
        results.append({
            "id": ws.id,
            "name": ws.name,
            "role": "owner",
            "role_display": "Owner",
            "is_owner": True,
            "can_write": True,
        })

    # Shared workspaces
    memberships = user.workspace_memberships.select_related("workspace", "workspace__owner").all()
    for mem in memberships:
        ws = mem.workspace
        results.append({
            "id": ws.id,
            "name": ws.name,
            "role": mem.role,
            "role_display": mem.get_role_display(),
            "is_owner": False,
            "can_write": mem.role == WorkspaceRole.EDITOR,
            "owner_name": ws.owner.username,
        })

    return results


def create_workspace(name: str, owner: Any) -> Workspace:
    """
    Create a new workspace and automatically provision its primary shopping list and meal plan.

    Args:
        name: Name for the workspace.
        owner: User instance who owns the workspace.

    Returns:
        The newly created Workspace.
    """
    workspace = Workspace.objects.create(name=name, owner=owner)

    # Provision primary active shopping list
    default_store = StoreLocation.objects.first()
    ShoppingList.objects.create(
        name=f"{name} Shopping List",
        workspace=workspace,
        owner=owner,
        is_preset=False,
        active_store=default_store,
    )

    # Provision primary meal plan
    MealPlan.objects.create(
        name=f"{name} Meal Plan",
        workspace=workspace,
        owner=owner,
    )

    return workspace


def share_workspace(workspace: Workspace, user: Any, role: str) -> WorkspaceMember:
    """
    Share a workspace with a user or update their existing role.

    Args:
        workspace: Target Workspace.
        user: Target User.
        role: WorkspaceRole choice ('viewer' or 'editor').

    Returns:
        The created or updated WorkspaceMember.
    """
    member, _ = WorkspaceMember.objects.update_or_create(
        workspace=workspace,
        user=user,
        defaults={"role": role},
    )
    return member


def remove_workspace_member(workspace: Workspace, user: Any) -> bool:
    """
    Remove a member's access to a workspace.

    Args:
        workspace: Target Workspace.
        user: User to remove.

    Returns:
        True if removed, False otherwise.
    """
    count, _ = WorkspaceMember.objects.filter(workspace=workspace, user=user).delete()
    return count > 0


def clear_workspace_data(
    workspace: Workspace,
    request: HttpRequest | None = None,
) -> dict[str, int]:
    """
    Clear all shopping list items on active shopping lists,
    unload all preset lists, and clear out all meals from meal plans in the workspace.

    Args:
        workspace: Target Workspace instance.
        request: Optional HttpRequest for audit attribution and WebSocket broadcasts.

    Returns:
        Dictionary with counts of cleared items:
        {"items_cleared": int, "presets_unloaded": int, "meals_cleared": int}
    """
    from apps.mealplans.services.mealplan_service import broadcast_mealplan_update, delete_meal_from_plan
    from apps.shopping.models import ShoppingListItem, ShoppingListItemSource
    from apps.shopping.services.broadcaster import broadcast_shopping_list_update
    from apps.shopping.services.preset_service import unload_preset_from_shopping_list

    primary_list = workspace.get_primary_list()

    # 1. Clear out all meal plans in the workspace
    meals_cleared = 0
    for mp in workspace.meal_plans.all():
        for meal in list(mp.meals.all()):
            delete_meal_from_plan(meal, shopping_list=primary_list, request=request)
            meals_cleared += 1

    # 2. Unload all preset lists from the workspace's shopping list(s)
    presets_unloaded = 0
    preset_lists = workspace.shopping_lists.filter(is_preset=True)
    for preset in preset_lists:
        if primary_list:
            unload_preset_from_shopping_list(preset, primary_list, request=request)
            presets_unloaded += 1

    # 3. Clear all items from all non-preset shopping lists in this workspace
    items_cleared = 0
    active_lists = workspace.shopping_lists.filter(is_preset=False)
    for sl in active_lists:
        items_count = sl.items.count()
        items_cleared += items_count
        ShoppingListItemSource.objects.filter(item__shopping_list=sl).delete()
        sl.items.all().delete()

    # 4. Broadcast real-time updates across open tabs and collaborating users
    actor_name = ""
    if request and getattr(request, "user", None) and request.user.is_authenticated:
        actor_name = (request.user.first_name or "").strip() or request.user.username
    if not actor_name:
        actor_name = "Someone"

    sender_id = ""
    if request:
        sender_id = request.headers.get("X-Client-Id") or request.META.get("HTTP_X_CLIENT_ID") or ""

    if primary_list:
        broadcast_shopping_list_update(
            shopping_list=primary_list,
            toast_message=f"🗑 {actor_name} cleared the workspace shopping list",
            actor_name=actor_name,
            sender_client_id=sender_id,
        )

    broadcast_mealplan_update(
        request=request,
        toast_message=f"🗑 {actor_name} cleared the workspace meal plan",
        shopping_list=primary_list,
        workspace=workspace,
    )

    return {
        "items_cleared": items_cleared,
        "presets_unloaded": presets_unloaded,
        "meals_cleared": meals_cleared,
    }
