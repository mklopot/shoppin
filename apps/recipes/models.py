"""
Data models for culinary recipes, ingredients, ratings, comments, and cooking logs.

Enables full recipe organization with difficulty ratings, equipment,
prep/cook times, nutritional/dietary tags, and social interactions.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify


class Recipe(models.Model):
    """
    A culinary recipe entry containing ingredients, instructions, and metadata.
    """
    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]

    # Core Identifiers
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    directions = models.TextField(blank=True)

    # Classifications & Tags
    cuisine = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. Mexican, American, German, Chinese",
    )
    dish_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. casserole, salad, stew, sandwich",
    )
    dietary_restrictions = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['dairy', 'vegetarian', 'kosher-parve', 'vegan']",
    )
    meal_type = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['dinner', 'lunch', 'side']",
    )
    occasions = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['summer', 'Christmas', 'birthday']",
    )

    # Cooking Specifications
    difficulty_level = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default="medium",
        blank=True,
    )
    portions = models.PositiveIntegerField(default=4, help_text="Number of portions/servings")
    prep_time_minutes = models.PositiveIntegerField(default=0, help_text="Prep time in minutes")
    cook_time_minutes = models.PositiveIntegerField(default=0, help_text="Cook time in minutes")
    special_equipment = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['Instant Pot', 'casserole dish', 'wok']",
    )
    storage_instructions = models.TextField(blank=True)
    reheating_instructions = models.TextField(blank=True)

    # Media & Reference
    photo_urls = models.JSONField(default=list, blank=True, help_text="List of photo URLs")
    bibliography = models.JSONField(
        default=list,
        blank=True,
        help_text="URLs, book references, or sources",
    )

    # Relationships
    serve_with = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="recommended_with",
        help_text="Complementary recipes to serve together",
    )
    variations = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=True,
        help_text="Linked recipe variations",
    )

    # Moderation & Visibility
    is_public = models.BooleanField(default=True)
    is_approved = models.BooleanField(
        default=True,
        help_text="Approved by moderator for public browse/search",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recipes",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs) -> None:
        """Auto-populate URL slug from name if not specified."""
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the recipe title."""
        return self.name

    @property
    def average_rating(self) -> float | None:
        """Calculate arithmetic mean of all submitted star ratings."""
        ratings = self.ratings.all()
        if not ratings:
            return None
        return round(sum(rating.stars for rating in ratings) / len(ratings), 1)


class Ingredient(models.Model):
    """
    An individual ingredient entry belonging to a recipe.
    """
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1.00"))
    amount_unit = models.CharField(max_length=50, blank=True)
    purpose = models.CharField(max_length=255, blank=True)
    optional = models.BooleanField(default=False)
    brand = models.CharField(max_length=100, blank=True)
    vendor = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=100, blank=True, default="other")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        """Format ingredient quantity and name."""
        unit_str = f" {self.amount_unit}" if self.amount_unit else ""
        return f"{self.amount:g}{unit_str} {self.name}"


class RecipeRating(models.Model):
    """
    User star rating (1 to 5) and binary recommendation for a recipe.
    """
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipe_ratings",
    )
    stars = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        default=5,
    )
    thumbs_up = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("recipe", "user")

    def __str__(self) -> str:
        """Return rating summary string."""
        return f"{self.recipe.name} - {self.stars}★ by {self.user}"


class RecipeComment(models.Model):
    """
    User text comment or review for a recipe.
    """
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipe_comments",
    )
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("recipe", "user")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Return comment summary string."""
        return f"Comment on {self.recipe.name} by {self.user}"


class RecipeMadeLog(models.Model):
    """
    Historical log of when a user cooked or prepared a recipe.
    """
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="made_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipe_made_logs",
    )
    made_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-made_at"]

    def __str__(self) -> str:
        """Return made log summary string."""
        return f"{self.recipe.name} made on {self.made_at.strftime('%Y-%m-%d')}"
