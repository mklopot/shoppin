"""
Models for the core application.

Defines multi-tenant Workspaces and membership sharing roles.
A Workspace encapsulates an active shopping list, preset lists, and a meal plan.
"""

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from apps.mealplans.models import MealPlan
    from apps.shopping.models import ShoppingList


class WorkspaceRole(models.TextChoices):
    """
    Access roles for shared workspace members.

    - VIEWER: Read-only access. Cannot mutate lists, items, or meal plans.
    - EDITOR: Read-write access. Can add, edit, and organize lists and meal plans.
    """
    VIEWER = "viewer", "Read-Only"
    EDITOR = "editor", "Read-Write"


class Workspace(models.Model):
    """
    A workspace encapsulating an active shopping list, a set of preset lists, and a meal plan.

    Can be shared with other users as read-only (viewer) or read-write (editor).
    """
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_workspaces",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        """Return the workspace name."""
        return self.name

    def get_user_role(self, user: Any) -> str | None:
        """
        Determine the access level of a user within this workspace.

        Args:
            user: Django user instance to inspect.

        Returns:
            'owner', 'editor', 'viewer', or None if the user has no access.
        """
        if not user or not user.is_authenticated:
            return None
        if self.owner_id == user.id or getattr(user, "is_superuser", False):
            return "owner"
        membership = self.memberships.filter(user=user).first()
        return membership.role if membership else None

    def can_write(self, user: Any) -> bool:
        """Return True if user has edit/write permissions (owner or editor)."""
        role = self.get_user_role(user)
        return role in ("owner", WorkspaceRole.EDITOR)

    def can_read(self, user: Any) -> bool:
        """Return True if user has at least read/view access."""
        return self.get_user_role(user) is not None

    def get_primary_list(self) -> "ShoppingList | None":
        """Retrieve the active primary household shopping list for this workspace."""
        return self.shopping_lists.filter(is_preset=False).first()

    def get_preset_lists(self) -> models.QuerySet["ShoppingList"]:
        """Retrieve all preset list templates belonging to this workspace."""
        return self.shopping_lists.filter(is_preset=True)

    def get_meal_plan(self) -> "MealPlan | None":
        """Retrieve the primary meal plan associated with this workspace."""
        return self.meal_plans.first()


class WorkspaceMember(models.Model):
    """
    Membership record defining a user's sharing permissions on a workspace.
    """
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.VIEWER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "user")
        ordering = ["workspace", "user"]

    def __str__(self) -> str:
        """Return human-readable membership description."""
        return f"{self.user} ({self.get_role_display()}) in {self.workspace.name}"


class TermsOfServiceAcceptance(models.Model):
    """
    Audit record of a user's binding acceptance of the Terms of Service,
    storing comprehensive client telemetry, network headers, and device specs.
    """
    CURRENT_VERSION = "2026.1-DRACONIAN"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tos_acceptances",
        null=True,
        blank=True,
    )
    version = models.CharField(max_length=64, default=CURRENT_VERSION)
    accepted_at = models.DateTimeField(auto_now_add=True)

    # Network & Geolocation Telemetry
    ip_address = models.CharField(max_length=128, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    geolocation = models.CharField(max_length=255, blank=True, default="")

    # Hardware & Screen Telemetry
    screen_resolution = models.CharField(max_length=64, blank=True, default="")
    viewport_size = models.CharField(max_length=64, blank=True, default="")
    color_depth = models.CharField(max_length=32, blank=True, default="")
    pixel_ratio = models.CharField(max_length=32, blank=True, default="")
    timezone = models.CharField(max_length=128, blank=True, default="")
    client_language = models.CharField(max_length=64, blank=True, default="")
    platform = models.CharField(max_length=128, blank=True, default="")
    hardware_concurrency = models.CharField(max_length=32, blank=True, default="")
    device_memory_gb = models.CharField(max_length=32, blank=True, default="")
    touch_support = models.BooleanField(default=False)

    # Comprehensive raw telemetry dump
    raw_telemetry = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-accepted_at"]
        verbose_name = "Terms of Service Acceptance"
        verbose_name_plural = "Terms of Service Acceptances"

    def __str__(self) -> str:
        username = self.user.username if self.user else "Anonymous"
        return f"TOS Acceptance v{self.version} by {username} at {self.accepted_at}"
