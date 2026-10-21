from django.contrib import admin

from apps.mealplans.models import Meal, MealPlan, MealPlanRule


class MealInline(admin.TabularInline):
    model = Meal
    extra = 1


class MealPlanRuleInline(admin.TabularInline):
    model = MealPlanRule
    extra = 1


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name",)
    inlines = [MealInline, MealPlanRuleInline]


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    list_display = ("name", "meal_plan", "emoji", "order")
    list_filter = ("meal_plan",)
