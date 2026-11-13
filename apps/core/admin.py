from typing import Any

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.core.models import (
    TermsOfServiceAcceptance,
    UserDMCAProfile,
    Workspace,
    WorkspaceMember,
)

User = get_user_model()


class WorkspaceMemberInline(admin.TabularInline):
    """Inline membership manager inside workspace change form."""
    model = WorkspaceMember
    extra = 1


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    """Admin interface for managing workspaces."""
    list_display = ("name", "owner", "created_at", "updated_at")
    search_fields = ("name", "owner__username", "owner__email")
    inlines = [WorkspaceMemberInline]


@admin.register(TermsOfServiceAcceptance)
class TermsOfServiceAcceptanceAdmin(admin.ModelAdmin):
    """Admin interface and audit log for Terms of Service acceptances."""
    list_display = ("user", "first_name", "last_name", "version", "accepted_at", "ip_address", "platform", "timezone")
    list_filter = ("version", "accepted_at", "platform")
    search_fields = ("user__username", "user__email", "first_name", "last_name", "ip_address", "user_agent")
    readonly_fields = ("accepted_at",)


class UserDMCAProfileInline(admin.StackedInline):
    """Inline DMCA copyright status editor inside the User admin change form."""
    model = UserDMCAProfile
    can_delete = False
    verbose_name = "DMCA Copyright Profile"
    verbose_name_plural = "DMCA Copyright Profile"
    fields = ("strikes", "is_banned", "strike_history", "updated_at")
    readonly_fields = ("updated_at",)


@admin.register(UserDMCAProfile)
class UserDMCAProfileAdmin(admin.ModelAdmin):
    """Stand-alone admin view for querying user DMCA records."""
    list_display = ("user", "strikes", "is_banned", "updated_at")
    list_filter = ("is_banned", "strikes")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """Enhanced User admin displaying DMCA strikes and repeat infringer status."""
    inlines = list(BaseUserAdmin.inlines) + [UserDMCAProfileInline]
    list_display = list(BaseUserAdmin.list_display) + ["get_dmca_strikes", "is_dmca_banned"]

    @admin.display(description="DMCA Strikes")
    def get_dmca_strikes(self, obj: Any) -> int:
        profile = getattr(obj, "dmca_profile", None)
        return profile.strikes if profile else 0

    @admin.display(description="DMCA Banned", boolean=True)
    def is_dmca_banned(self, obj: Any) -> bool:
        profile = getattr(obj, "dmca_profile", None)
        return bool(profile and profile.is_banned)

