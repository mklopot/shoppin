"""
URL routing patterns for the Meal Plans application.
"""

from django.urls import path

from apps.mealplans import views

app_name = "mealplans"

urlpatterns = [
    path("", views.meal_plan_view, name="detail"),
    path("meal/add/", views.add_meal, name="add_meal"),
    path("meal/<int:meal_id>/delete/", views.delete_meal, name="delete_meal"),
    path("meal/<int:meal_id>/add-dish/", views.add_dish, name="add_dish"),
    path("meal/<int:meal_id>/dish/<int:recipe_id>/delete/", views.delete_dish, name="delete_dish"),
    path("clear/", views.clear_meal_plan, name="clear"),
    path("recipe/<int:recipe_id>/modal/", views.recipe_modal, name="recipe_modal"),
]
