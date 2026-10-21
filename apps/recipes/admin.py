from django.contrib import admin

from apps.recipes.models import (
    Ingredient,
    Recipe,
    RecipeComment,
    RecipeMadeLog,
    RecipeRating,
)


class IngredientInline(admin.TabularInline):
    model = Ingredient
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "cuisine",
        "dish_type",
        "difficulty_level",
        "portions",
        "is_public",
        "is_approved",
        "created_at",
    )
    list_filter = ("is_public", "is_approved", "difficulty_level", "cuisine", "dish_type")
    search_fields = ("name", "description", "directions", "cuisine", "dish_type")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [IngredientInline]
    actions = ["approve_recipes"]

    @admin.action(description="Approve selected recipes for public browse")
    def approve_recipes(self, request, queryset):
        queryset.update(is_approved=True)


@admin.register(RecipeRating)
class RecipeRatingAdmin(admin.ModelAdmin):
    list_display = ("recipe", "user", "stars", "thumbs_up", "created_at")
    list_filter = ("stars", "thumbs_up")


@admin.register(RecipeComment)
class RecipeCommentAdmin(admin.ModelAdmin):
    list_display = ("recipe", "user", "created_at")
    search_fields = ("comment", "recipe__name", "user__username")


@admin.register(RecipeMadeLog)
class RecipeMadeLogAdmin(admin.ModelAdmin):
    list_display = ("recipe", "user", "made_at")
