"""
Core views for landing, workspace management, and development persona switching.
"""


from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Workspace, WorkspaceRole
from apps.core.services.workspace_service import (
    create_workspace as create_workspace_record,
)
from apps.core.services.workspace_service import (
    remove_workspace_member,
)
from apps.core.services.workspace_service import (
    share_workspace as share_workspace_record,
)

User = get_user_model()


def index(request: HttpRequest) -> HttpResponse:
    """Render the main application landing page or redirect to shopping list."""
    return redirect("shopping:list")


def switch_workspace(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """
    Switch the active workspace for the current user's session.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.

    Returns:
        Redirect back to previous page or shopping list.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if not workspace.can_read(request.user):
        return HttpResponseForbidden("You do not have access to this workspace.")

    request.session["active_workspace_id"] = workspace.id

    referer = request.META.get("HTTP_REFERER")
    if referer:
        # Strip any existing workspace_id query param to prevent overriding session
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
        parsed = urlsplit(referer)
        query = parse_qs(parsed.query)
        query.pop("workspace_id", None)
        new_query = urlencode(query, doseq=True)
        cleaned_url = urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            new_query,
            parsed.fragment,
        ))
        return redirect(cleaned_url)
    return redirect("shopping:list")


@require_POST
def create_workspace_view(request: HttpRequest) -> HttpResponse:
    """
    Handle POST request to create a new workspace with primary list and meal plan.

    Args:
        request: HttpRequest instance.

    Returns:
        Redirect back to shopping list with the new workspace active.
    """
    creator = request.user
    if not creator.is_authenticated:
        if settings.DEBUG:
            dev_user = (
                User.objects.filter(username="admin").first()
                or User.objects.filter(is_superuser=True).first()
                or User.objects.first()
            )
            if dev_user:
                login(request, dev_user)
                creator = dev_user
        if not creator or not creator.is_authenticated:
            return HttpResponseForbidden("Must be logged in to create a workspace.")

    name = request.POST.get("name", "").strip()
    if not name:
        name = "My Workspace"

    workspace = create_workspace_record(name=name, owner=creator)
    request.session["active_workspace_id"] = workspace.id

    return redirect("shopping:list")


def workspace_members_modal(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """
    Render HTMX modal for managing collaborators and viewing sharing roles.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.

    Returns:
        HTML snippet for modal rendering.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if not workspace.can_read(request.user):
        return HttpResponseForbidden("Access denied.")

    is_owner = (workspace.owner_id == request.user.id) or getattr(request.user, "is_superuser", False)
    memberships = workspace.memberships.select_related("user").all()

    # Find candidate users who are not the owner and not yet members
    existing_user_ids = {workspace.owner_id} | set(memberships.values_list("user_id", flat=True))
    available_users = User.objects.exclude(id__in=existing_user_ids).order_by("username")

    context = {
        "workspace": workspace,
        "is_owner": is_owner,
        "memberships": memberships,
        "available_users": available_users,
        "roles": WorkspaceRole.choices,
    }
    return render(request, "core/partials/workspace_members_modal.html", context)


@require_POST
def share_workspace_view(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """
    Add or update a collaborator's role in a workspace.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.

    Returns:
        Updated members modal partial.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if workspace.get_user_role(request.user) != "owner":
        return HttpResponseForbidden("Only the workspace owner can manage members.")

    user_id = request.POST.get("user_id")
    username = request.POST.get("username", "").strip()
    role = request.POST.get("role", WorkspaceRole.VIEWER)

    target_user = None
    if user_id:
        target_user = User.objects.filter(id=user_id).first()
    elif username:
        target_user = User.objects.filter(username=username).first()

    if target_user and target_user.id != workspace.owner_id:
        share_workspace_record(workspace=workspace, user=target_user, role=role)

    return workspace_members_modal(request, workspace_id)


@require_POST
def remove_member_view(request: HttpRequest, workspace_id: int, user_id: int) -> HttpResponse:
    """
    Remove a member's access from a workspace.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.
        user_id: Member user primary key.

    Returns:
        Updated members modal partial.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if workspace.get_user_role(request.user) != "owner":
        return HttpResponseForbidden("Only the workspace owner can manage members.")

    target_user = get_object_or_404(User, id=user_id)
    remove_workspace_member(workspace=workspace, user=target_user)

    return workspace_members_modal(request, workspace_id)


def switch_persona(request: HttpRequest, username: str) -> HttpResponse:
    """
    Switch active authenticated user in development mode without credentials.

    Guarded strictly by DEBUG setting.

    Args:
        request: HttpRequest instance.
        username: Target persona username (e.g. 'alice', 'bob').

    Returns:
        Redirect back to previous page.
    """
    if not settings.DEBUG:
        return HttpResponseForbidden("Persona switcher is disabled in production.")

    user = get_object_or_404(User, username=username)
    login(request, user)

    # Reset active workspace session so it defaults to the newly logged-in user's workspace
    if "active_workspace_id" in request.session:
        del request.session["active_workspace_id"]

    referer = request.META.get("HTTP_REFERER")
    if referer:
        # Strip workspace_id query param so new user doesn't get 403 on previous user's private workspace
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
        parsed = urlsplit(referer)
        query = parse_qs(parsed.query)
        query.pop("workspace_id", None)
        new_query = urlencode(query, doseq=True)
        cleaned_url = urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            new_query,
            parsed.fragment,
        ))
        return redirect(cleaned_url)
    return redirect("shopping:list")
