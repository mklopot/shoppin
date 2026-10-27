"""
Context processors for multi-tenant Workspace navigation and persona switching.
"""

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest

from apps.core.services.workspace_service import get_active_workspace, get_user_workspaces

User = get_user_model()


def workspace_context(request: HttpRequest) -> dict[str, Any]:
    """
    Expose active workspace, accessible workspaces, permissions, and dev personas to templates.

    Args:
        request: HttpRequest instance.

    Returns:
        Dictionary of template context variables.
    """
    ws = get_active_workspace(request)
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        role = ws.get_user_role(user) if ws else "owner"
        can_write = ws.can_write(user) if ws else True
    else:
        role = "guest"
        can_write = False
    is_owner = (role == "owner")

    user_workspaces = get_user_workspaces(user) if user else []

    personas = [
        {"username": "admin", "label": "Admin", "role": "Owner of Home"},
        {"username": "alice", "label": "Alice", "role": "Editor in Home"},
        {"username": "bob", "label": "Bob", "role": "Viewer in Home"},
        {"username": "carol", "label": "Carol", "role": "External Guest"},
    ]

    return {
        "active_workspace": ws,
        "workspace_role": role,
        "can_write_workspace": can_write,
        "is_workspace_owner": is_owner,
        "user_workspaces": user_workspaces,
        "dev_personas": personas,
        "debug_mode": settings.DEBUG,
    }
