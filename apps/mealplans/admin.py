"""
Django admin configuration for meal plans, meals, and scheduling rules.
"""

from django.contrib import admin

from apps.mealplans.models import Meal, MealPlan, MealPlanRule


class MealInline(admin.TabularInline):
    """Inline meal editor inside a meal plan form."""
    model = Meal
    extra = 1


class MealPlanRuleInline(admin.TabularInline):
    """Inline rule editor inside a meal plan form."""
    model = MealPlanRule
    extra = 1


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    """Admin manager for meal plan schedules."""
    list_display = ("name", "owner", "created_at")
    search_fields = ("name",)
    inlines = [MealInline, MealPlanRuleInline]


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    """Admin manager for planned meals."""
    list_display = ("name", "meal_plan", "emoji", "order")
    list_filter = ("meal_plan",)
