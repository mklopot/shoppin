"""
URL routing patterns for the Recipes application.
"""

from django.urls import path

from apps.recipes import views

app_name = "recipes"

urlpatterns = [
    path("", views.recipe_list_view, name="list"),
    path("create/", views.recipe_create_view, name="create"),
    path("<int:recipe_id>/", views.recipe_detail_view, name="detail"),
    path("<int:recipe_id>/edit/", views.recipe_edit_view, name="edit"),
    path("<int:recipe_id>/delete/", views.recipe_delete_view, name="delete"),
    path("<int:recipe_id>/rate/", views.recipe_rate_view, name="rate"),
    path("<int:recipe_id>/add-to-shopping-list/", views.recipe_add_to_shopping_list_view, name="add_to_shopping"),
    path("<int:recipe_id>/add-to-mealplan/", views.recipe_add_to_mealplan_view, name="add_to_mealplan"),
]
