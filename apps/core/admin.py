from django.contrib import admin

from apps.core.models import TermsOfServiceAcceptance, Workspace, WorkspaceMember


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
