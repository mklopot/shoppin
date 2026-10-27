"""
URL routing patterns for the Recipes application.
"""

from django.urls import path

from apps.recipes import views

app_name = "recipes"

urlpatterns = [
    path("", views.recipe_list_view, name="list"),
    path("create/", views.recipe_create_view, name="create"),
    path("import-url/", views.recipe_import_url_view, name="import_url"),
    path("<int:recipe_id>/", views.recipe_detail_view, name="detail"),
    path("<slug:slug>/", views.recipe_detail_view, name="detail_slug"),
    path("<int:recipe_id>/edit/", views.recipe_edit_view, name="edit"),
    path("<slug:slug>/edit/", views.recipe_edit_view, name="edit_slug"),
    path("<int:recipe_id>/delete/", views.recipe_delete_view, name="delete"),
    path("<slug:slug>/delete/", views.recipe_delete_view, name="delete_slug"),
    path("<int:recipe_id>/rate/", views.recipe_rate_view, name="rate"),
    path("<slug:slug>/rate/", views.recipe_rate_view, name="rate_slug"),
    path("<int:recipe_id>/prompt-mealplan/", views.recipe_prompt_mealplan_view, name="prompt_add_to_mealplan"),
    path("<slug:slug>/prompt-mealplan/", views.recipe_prompt_mealplan_view, name="prompt_add_to_mealplan_slug"),
    path("<int:recipe_id>/add-to-mealplan/", views.recipe_add_to_mealplan_view, name="add_to_mealplan"),
    path("<slug:slug>/add-to-mealplan/", views.recipe_add_to_mealplan_view, name="add_to_mealplan_slug"),
]
