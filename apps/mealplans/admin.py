"""
Django admin configuration for meal plans, meals, and scheduling rules.
"""

from django.contrib import admin

from apps.mealplans.models import ArchivedMeal, ArchivedMealDish, Meal, MealPlan, MealPlanRule


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


class ArchivedMealDishInline(admin.TabularInline):
    """Inline view of dishes belonging to an archived meal."""
    model = ArchivedMealDish
    extra = 0


@admin.register(ArchivedMeal)
class ArchivedMealAdmin(admin.ModelAdmin):
    """Admin manager for workspace archived meals."""
    list_display = ("name", "workspace", "made_by_name", "rating", "made_at")
    list_filter = ("workspace", "made_at")
    search_fields = ("name", "dishes__dish_name", "dishes__ingredient_names_text")
    inlines = [ArchivedMealDishInline]
