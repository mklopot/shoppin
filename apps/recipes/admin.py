"""
Django admin configuration for recipes and related social models.
"""

from django.contrib import admin

from apps.recipes.models import (
    Ingredient,
    Recipe,
    RecipeComment,
    RecipeMadeLog,
    RecipeRating,
)


class IngredientInline(admin.TabularInline):
    """Inline ingredient editor inside the recipe admin change form."""
    model = Ingredient
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    """Admin interface for managing recipes and their ingredients."""
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
    list_editable = ("is_public", "is_approved")
    list_filter = ("is_public", "is_approved", "difficulty_level", "cuisine", "dish_type")
    search_fields = ("name", "description", "directions", "cuisine", "dish_type")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [IngredientInline]
    actions = ["approve_recipes", "revoke_approval", "make_public", "make_private"]

    @admin.action(description="Approve selected recipes for public browse")
    def approve_recipes(self, request, queryset):
        """Batch approve recipes for public view."""
        count = queryset.update(is_approved=True)
        self.message_user(request, f"{count} recipe(s) approved for public browsing.")

    @admin.action(description="Revoke approval for selected recipes")
    def revoke_approval(self, request, queryset):
        """Batch revoke approval."""
        count = queryset.update(is_approved=False)
        self.message_user(request, f"{count} recipe(s) marked unapproved.")

    @admin.action(description="Mark selected recipes as Public")
    def make_public(self, request, queryset):
        """Batch make public."""
        count = queryset.update(is_public=True)
        self.message_user(request, f"{count} recipe(s) set to Public.")

    @admin.action(description="Mark selected recipes as Private")
    def make_private(self, request, queryset):
        """Batch make private."""
        count = queryset.update(is_public=False)
        self.message_user(request, f"{count} recipe(s) set to Private.")


@admin.register(RecipeRating)
class RecipeRatingAdmin(admin.ModelAdmin):
    """Admin interface for recipe user ratings."""
    list_display = ("recipe", "user", "stars", "thumbs_up", "created_at")
    list_filter = ("stars", "thumbs_up")


@admin.register(RecipeComment)
class RecipeCommentAdmin(admin.ModelAdmin):
    """Admin interface for recipe user comments."""
    list_display = ("recipe", "user", "created_at")
    search_fields = ("comment", "recipe__name", "user__username")


@admin.register(RecipeMadeLog)
class RecipeMadeLogAdmin(admin.ModelAdmin):
    """Admin interface for user cooking history logs."""
    list_display = ("recipe", "user", "made_at")
    search_fields = ("recipe__name", "user__username")
