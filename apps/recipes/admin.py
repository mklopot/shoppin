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
    RecipeUserPhoto,
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
        "photo_approved",
        "difficulty_level",
        "portions",
        "is_public",
        "is_approved",
        "is_web_imported",
        "copyright_cleared",
        "created_at",
    )
    list_editable = ("is_public", "is_approved", "photo_approved", "copyright_cleared")
    list_filter = (
        "is_public",
        "is_approved",
        "is_web_imported",
        "copyright_cleared",
        "photo_approved",
        "difficulty_level",
        "cuisine",
        "dish_type",
    )
    search_fields = ("name", "description", "directions", "cuisine", "dish_type")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [IngredientInline]
    actions = [
        "approve_recipes",
        "revoke_approval",
        "verify_copyright",
        "revoke_copyright",
        "make_public",
        "make_private",
        "approve_recipe_photos",
        "hide_recipe_photos",
    ]

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

    @admin.action(description="Verify as re-worded & non-infringing")
    def verify_copyright(self, request, queryset):
        """Batch verify web-imported recipes as re-worded and non-infringing."""
        count = queryset.update(copyright_cleared=True)
        self.message_user(request, f"{count} recipe(s) verified as re-worded & non-infringing.")

    @admin.action(description="Revoke copyright clearance")
    def revoke_copyright(self, request, queryset):
        """Batch revoke copyright clearance."""
        count = queryset.update(copyright_cleared=False)
        self.message_user(request, f"{count} recipe(s) copyright clearance revoked.")

    @admin.action(description="Mark selected recipes as Public")
    def make_public(self, request, queryset):
        """Batch make public (unverified web-imported recipes remain private)."""
        unverified = queryset.filter(is_web_imported=True, copyright_cleared=False)
        unverified_count = unverified.count()
        if unverified_count > 0:
            from django.contrib import messages
            self.message_user(
                request,
                f"Skipped {unverified_count} recipe(s): web-imported recipes must be verified as non-infringing before being made public.",
                level=messages.WARNING,
            )
        eligible = queryset.exclude(is_web_imported=True, copyright_cleared=False)
        count = eligible.update(is_public=True)
        self.message_user(request, f"{count} recipe(s) set to Public.")

    @admin.action(description="Mark selected recipes as Private")
    def make_private(self, request, queryset):
        """Batch make private."""
        count = queryset.update(is_public=False)
        self.message_user(request, f"{count} recipe(s) set to Private.")

    @admin.action(description="Approve uploaded main recipe photos")
    def approve_recipe_photos(self, request, queryset):
        """Batch approve main recipe photos held for moderation."""
        count = queryset.update(photo_approved=True)
        self.message_user(request, f"{count} recipe photo(s) approved.")

    @admin.action(description="Hide uploaded main recipe photos")
    def hide_recipe_photos(self, request, queryset):
        """Batch hide main recipe photos."""
        count = queryset.update(photo_approved=False)
        self.message_user(request, f"{count} recipe photo(s) hidden.")


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
    list_display = ("recipe", "user", "workspace", "made_at")
    list_filter = ("workspace",)
    search_fields = ("recipe__name", "user__username", "workspace__name")


@admin.register(RecipeUserPhoto)
class RecipeUserPhotoAdmin(admin.ModelAdmin):
    """Admin interface for moderating user-submitted dish photos."""
    list_display = ("recipe", "user", "workspace", "caption", "is_approved", "created_at")
    list_editable = ("is_approved",)
    list_filter = ("is_approved", "workspace")
    search_fields = ("recipe__name", "user__username", "submitted_by_name", "caption")
    actions = ["approve_photos", "hide_photos"]

    @admin.action(description="Approve selected user-submitted photos")
    def approve_photos(self, request, queryset):
        """Batch approve user-submitted dish photos."""
        count = queryset.update(is_approved=True)
        self.message_user(request, f"{count} user photo(s) approved.")

    @admin.action(description="Hide selected user-submitted photos")
    def hide_photos(self, request, queryset):
        """Batch hide user-submitted dish photos."""
        count = queryset.update(is_approved=False)
        self.message_user(request, f"{count} user photo(s) hidden.")
