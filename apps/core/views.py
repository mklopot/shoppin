"""
Core views for landing, workspace management, and development persona switching.
"""


from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    if not creator or not creator.is_authenticated:
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


def _render_workspace_modal(
    request: HttpRequest,
    workspace: Workspace,
    active_tab: str = "settings",
    settings_saved: bool = False,
    purged_count: int = 0,
) -> HttpResponse:
    """Helper to render the unified workspace settings and members modal."""
    is_owner = (workspace.owner_id == request.user.id) or getattr(request.user, "is_superuser", False)
    memberships = workspace.memberships.select_related("user").all()

    existing_user_ids = {workspace.owner_id} | set(memberships.values_list("user_id", flat=True))
    available_users = User.objects.exclude(id__in=existing_user_ids).order_by("username")

    retention_choices = [
        (1, "1 day (24 hours)"),
        (3, "3 days"),
        (7, "1 week (7 days) - Default"),
        (14, "2 weeks (14 days)"),
        (30, "1 month (30 days)"),
        (0, "Never (Keep indefinitely)"),
    ]

    context = {
        "workspace": workspace,
        "is_owner": is_owner,
        "memberships": memberships,
        "available_users": available_users,
        "roles": WorkspaceRole.choices,
        "active_tab": active_tab,
        "retention_choices": retention_choices,
        "settings_saved": settings_saved,
        "purged_count": purged_count,
    }
    return render(request, "core/partials/workspace_members_modal.html", context)


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

    tab = request.GET.get("tab", "members")
    return _render_workspace_modal(request, workspace, active_tab=tab)


def workspace_settings_modal(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """
    Render HTMX modal for configuring workspace settings and item cleanup policies.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.

    Returns:
        HTML snippet for modal rendering with settings tab active.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if not workspace.can_read(request.user):
        return HttpResponseForbidden("Access denied.")

    tab = request.GET.get("tab", "settings")
    return _render_workspace_modal(request, workspace, active_tab=tab)


@require_POST
def update_workspace_settings_view(request: HttpRequest, workspace_id: int) -> HttpResponse:
    """
    Update workspace configuration including item retention policies and name.

    Args:
        request: HttpRequest instance.
        workspace_id: Target workspace primary key.

    Returns:
        Updated workspace modal partial.
    """
    workspace = get_object_or_404(Workspace, id=workspace_id)
    if workspace.get_user_role(request.user) != "owner":
        return HttpResponseForbidden("Only the workspace owner can update workspace settings.")

    name = request.POST.get("name", "").strip()
    if name:
        workspace.name = name

    retention_raw = request.POST.get("completed_items_retention_days")
    if retention_raw is not None and retention_raw != "":
        try:
            workspace.completed_items_retention_days = max(0, int(retention_raw))
        except (ValueError, TypeError):
            pass

    workspace.save()

    from apps.shopping.services.cleanup_service import purge_expired_completed_items
    purged_count = purge_expired_completed_items(workspace)
    if purged_count > 0:
        primary_list = workspace.get_primary_list()
        if primary_list:
            from apps.shopping.services.broadcaster import broadcast_shopping_list_update
            broadcast_shopping_list_update(
                shopping_list=primary_list,
                toast_message=None,
            )

    return _render_workspace_modal(
        request,
        workspace,
        active_tab="settings",
        settings_saved=True,
        purged_count=purged_count,
    )


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

    return _render_workspace_modal(request, workspace, active_tab="members")


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

    return _render_workspace_modal(request, workspace, active_tab="members")


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

    # Automatically ensure TOS acceptance for dev personas to allow seamless local testing
    from apps.core.models import TermsOfServiceAcceptance
    from apps.core.services.tos_service import has_user_accepted_latest_tos, record_tos_acceptance

    if not has_user_accepted_latest_tos(user, request.session):
        record_tos_acceptance(user, request)
    request.session["tos_accepted"] = TermsOfServiceAcceptance.CURRENT_VERSION

    # Reset active workspace session so it defaults to the newly logged-in user's workspace
    if "active_workspace_id" in request.session:
        del request.session["active_workspace_id"]

    from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

    next_url = request.GET.get("next")
    referer = request.META.get("HTTP_REFERER")

    disallowed_prefixes = (
        "/terms",
        "/core/terms",
        "/login",
        "/accounts/login",
        "/core/login",
        "/logout",
        "/accounts/logout",
        "/core/logout",
        "/core/dev/switch-persona",
    )

    if not next_url and referer:
        parsed = urlsplit(referer)
        query = parse_qs(parsed.query)
        # If referer was e.g. login with ?next=/recipes/, use that next param
        if "next" in query and query["next"]:
            cand = query["next"][0]
            if cand.startswith("/") and not any(cand.startswith(p) for p in disallowed_prefixes):
                next_url = cand

        if not next_url:
            path = parsed.path
            if path.startswith("/") and not any(path.startswith(p) for p in disallowed_prefixes):
                query.pop("workspace_id", None)
                new_query = urlencode(query, doseq=True)
                next_url = urlunsplit(("", "", parsed.path, new_query, parsed.fragment))

    if not next_url or not next_url.startswith("/") or any(next_url.startswith(p) for p in disallowed_prefixes):
        next_url = reverse("shopping:list")

    return redirect(next_url)


def health_check(request: HttpRequest) -> JsonResponse:
    """
    Lightweight healthcheck endpoint for monitoring and reverse proxy verification.
    Verifies HTTP responsiveness and basic database connectivity.
    """
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
        return JsonResponse({"status": "healthy", "database": "connected"}, status=200)
    except Exception as exc:
        return JsonResponse({"status": "unhealthy", "error": str(exc)}, status=503)
