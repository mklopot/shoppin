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


def get_active_workspace(request: HttpRequest | None = None) -> Workspace:
    """
    Resolve the currently active Workspace for the request.

    Checks explicit query params (?workspace_id=X), session state,
    and falls back to user's first available workspace. If none exist,
    a personal workspace is automatically initialized.

    Args:
        request: Django HttpRequest or None.

    Returns:
        The active Workspace instance.
    """
    user = getattr(request, "user", None)

    # If unauthenticated, fallback to the primary default workspace
    if not user or not user.is_authenticated:
        ws = (
            Workspace.objects.filter(name="Home").first()
            or Workspace.objects.filter(owner__is_superuser=True).first()
            or Workspace.objects.first()
        )
        if not ws:
            default_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
            if not default_user:
                default_user = User.objects.create(username="default_user")
            ws = create_workspace("Main Workspace", default_user)
        return ws

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
        ws = Workspace.objects.first()
        return [{"id": ws.id, "name": ws.name, "role": "owner", "is_owner": True}] if ws else []

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
