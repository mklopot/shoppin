"""
URL routing patterns for the Shopping application.
"""

from django.urls import path

from apps.shopping import views

app_name = "shopping"

urlpatterns = [
    path("", views.shopping_list_view, name="list"),
    path("pantry-check/", views.pantry_check_view, name="pantry_check"),
    path("item/add/", views.add_item, name="add_item"),
    path("item/<int:item_id>/status/<str:new_status>/", views.set_item_status, name="set_status"),
    path("item/<int:item_id>/edit/", views.edit_item, name="edit_item"),
    path("item/<int:item_id>/delete/", views.delete_item, name="delete_item"),
    path("item/<int:item_id>/lock/", views.toggle_lock_item, name="toggle_lock"),
    path("set-store/", views.set_store, name="set_store"),
    path("nearest-store/", views.find_nearest_store, name="nearest_store"),
    path("reorder/", views.reorder_items, name="reorder"),
    path("reorder-sections/", views.reorder_sections, name="reorder_sections"),
]
