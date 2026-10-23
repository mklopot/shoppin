"""
URL routing patterns for the Shopping application.
"""

from django.urls import path

from apps.shopping import views, views_preset

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
    # Preset Lists Routes
    path("preset-lists/", views_preset.preset_list_index, name="preset_list_index"),
    path("preset-lists/create/", views_preset.preset_create, name="preset_create"),
    path("preset-lists/<int:preset_id>/", views_preset.preset_detail, name="preset_detail"),
    path("preset-lists/<int:preset_id>/edit-name/", views_preset.preset_edit_name, name="preset_edit_name"),
    path("preset-lists/<int:preset_id>/delete/", views_preset.preset_delete, name="preset_delete"),
    path("preset-lists/<int:preset_id>/items/add/", views_preset.preset_add_item, name="preset_add_item"),
    path("preset-lists/<int:preset_id>/items/<int:item_id>/edit/", views_preset.preset_edit_item, name="preset_edit_item"),
    path("preset-lists/<int:preset_id>/items/<int:item_id>/delete/", views_preset.preset_delete_item, name="preset_delete_item"),
    path("preset-lists/<int:preset_id>/schedule/", views_preset.preset_update_schedule, name="preset_update_schedule"),
    path("preset-lists/<int:preset_id>/run-schedule-now/", views_preset.preset_run_schedule_now, name="preset_run_schedule_now"),
    path("preset-lists/<int:preset_id>/load-modal/", views_preset.preset_load_modal, name="preset_load_modal"),
    path("preset-lists/<int:preset_id>/load/", views_preset.preset_load_items, name="preset_load_items"),
]
