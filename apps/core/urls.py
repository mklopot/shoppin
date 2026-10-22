"""
URL routing patterns for Core workspace and persona management.
"""

from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.index, name="index"),
    path("workspace/switch/<int:workspace_id>/", views.switch_workspace, name="switch_workspace"),
    path("workspace/create/", views.create_workspace_view, name="create_workspace"),
    path("workspace/<int:workspace_id>/members/", views.workspace_members_modal, name="workspace_members"),
    path("workspace/<int:workspace_id>/share/", views.share_workspace_view, name="share_workspace"),
    path("workspace/<int:workspace_id>/members/<int:user_id>/remove/", views.remove_member_view, name="remove_member"),
    path("dev/switch-persona/<str:username>/", views.switch_persona, name="switch_persona"),
]
