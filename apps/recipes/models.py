"""
Data models for culinary recipes, ingredients, ratings, comments, and cooking logs.

Enables full recipe organization with difficulty ratings, equipment,
prep/cook times, nutritional/dietary tags, and social interactions.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
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
    times_made = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this recipe has been prepared/cooked",
    )
    special_equipment = models.JSONField(
        default=list,
        blank=True,
        help_text="e.g. ['Instant Pot', 'casserole dish', 'wok']",
    )
    storage_instructions = models.TextField(blank=True)
    reheating_instructions = models.TextField(blank=True)

    # Nutritional Analysis (Approximate, per serving)
    calories_per_serving = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Approximate calories (kcal) per serving",
    )
    protein_per_serving_g = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        db_index=True,
        help_text="Approximate protein in grams per serving",
    )
    carbs_per_serving_g = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        db_index=True,
        help_text="Approximate carbohydrates in grams per serving",
    )
    fat_per_serving_g = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        db_index=True,
        help_text="Approximate total fat in grams per serving",
    )
    fiber_per_serving_g = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        blank=True,
        help_text="Approximate dietary fiber in grams per serving",
    )
    sodium_per_serving_mg = models.PositiveIntegerField(
        default=0,
        blank=True,
        help_text="Approximate sodium in milligrams per serving",
    )
    nutrition_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed nutritional breakdown, macro percentages, and per-ingredient items",
    )

    # Media & Reference
    photo_urls = models.JSONField(default=list, blank=True, help_text="List of photo URLs")
    photo_file = models.ImageField(
        upload_to="recipes/photos/",
        blank=True,
        null=True,
        help_text="Uploaded photo of the prepared dish",
    )
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

    def clean(self) -> None:
        """Validate that all recipe fields are free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

    def save(self, *args, **kwargs) -> None:
        """Auto-populate URL slug from name if not specified and ensure uniqueness."""
        if not self.slug:
            base_slug = slugify(self.name) or "recipe"
            slug = base_slug
            counter = 1
            while Recipe.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        """Return the recipe title."""
        return self.name

    def get_absolute_url(self) -> str:
        """Return straightforward public URL for this recipe."""
        if self.slug:
            return reverse("recipes:detail_slug", kwargs={"slug": self.slug})
        return reverse("recipes:detail", kwargs={"recipe_id": self.id})

    @property
    def average_rating(self) -> float | None:
        """Calculate arithmetic mean of all submitted star ratings."""
        ratings = self.ratings.all()
        if not ratings:
            return None
        return round(sum(rating.stars for rating in ratings) / len(ratings), 1)

    @property
    def primary_photo_url(self) -> str:
        """Return the primary photo URL (uploaded file or external URL) if available, else empty string."""
        if self.photo_file:
            try:
                url = self.photo_file.url
                if self.updated_at:
                    return f"{url}?v={int(self.updated_at.timestamp())}"
                return url
            except ValueError:
                pass
        if self.photo_urls and len(self.photo_urls) > 0:
            url = self.photo_urls[0]
            if url.startswith("/media/") and self.updated_at:
                return f"{url}?v={int(self.updated_at.timestamp())}"
            return url
        return ""

    @property
    def thumbs_up_count(self) -> int:
        """Count of thumbs-up endorsements."""
        return self.ratings.filter(thumbs_up=True).count()

    @property
    def rating_count(self) -> int:
        """Count of all ratings submitted."""
        return self.ratings.count()

    @property
    def total_time_minutes(self) -> int:
        """Total time required combining prep and cook times."""
        return (self.prep_time_minutes or 0) + (self.cook_time_minutes or 0)

    @property
    def directions_steps(self) -> list[str]:
        """Split directions text into list of clean steps."""
        if not self.directions:
            return []
        lines = [line.strip() for line in self.directions.splitlines() if line.strip()]
        return lines

    @property
    def has_nutrition(self) -> bool:
        """Check if nutritional analysis is available."""
        return (self.calories_per_serving or 0) > 0 or bool(self.nutrition_data)

    @property
    def total_calories(self) -> int:
        """Total calories for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return int(self.nutrition_data["total_recipe"].get("calories", (self.calories_per_serving or 0) * max(1, self.portions or 1)))
        return int((self.calories_per_serving or 0) * max(1, self.portions or 1))

    @property
    def total_protein_g(self) -> float:
        """Total protein for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return float(self.nutrition_data["total_recipe"].get("protein_g", float(self.protein_per_serving_g or 0) * max(1, self.portions or 1)))
        return round(float(self.protein_per_serving_g or 0) * max(1, self.portions or 1), 1)

    @property
    def total_carbs_g(self) -> float:
        """Total carbohydrates for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return float(self.nutrition_data["total_recipe"].get("carbs_g", float(self.carbs_per_serving_g or 0) * max(1, self.portions or 1)))
        return round(float(self.carbs_per_serving_g or 0) * max(1, self.portions or 1), 1)

    @property
    def total_fat_g(self) -> float:
        """Total fat for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return float(self.nutrition_data["total_recipe"].get("fat_g", float(self.fat_per_serving_g or 0) * max(1, self.portions or 1)))
        return round(float(self.fat_per_serving_g or 0) * max(1, self.portions or 1), 1)

    @property
    def total_fiber_g(self) -> float:
        """Total fiber for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return float(self.nutrition_data["total_recipe"].get("fiber_g", float(self.fiber_per_serving_g or 0) * max(1, self.portions or 1)))
        return round(float(self.fiber_per_serving_g or 0) * max(1, self.portions or 1), 1)

    @property
    def total_sodium_mg(self) -> int:
        """Total sodium for the entire recipe dish."""
        if self.nutrition_data and "total_recipe" in self.nutrition_data:
            return int(self.nutrition_data["total_recipe"].get("sodium_mg", (self.sodium_per_serving_mg or 0) * max(1, self.portions or 1)))
        return int((self.sodium_per_serving_mg or 0) * max(1, self.portions or 1))

    @property
    def macro_percentages(self) -> dict[str, int]:
        """
        Caloric percentage split between Protein (4 kcal/g), Carbs (4 kcal/g), and Fat (9 kcal/g).
        """
        if self.nutrition_data and "macro_percentages" in self.nutrition_data:
            return self.nutrition_data["macro_percentages"]

        p_cals = float(self.protein_per_serving_g or 0) * 4.0
        c_cals = float(self.carbs_per_serving_g or 0) * 4.0
        f_cals = float(self.fat_per_serving_g or 0) * 9.0
        sum_cals = p_cals + c_cals + f_cals

        if sum_cals <= 0:
            return {"protein_pct": 0, "carbs_pct": 0, "fat_pct": 0}

        p_pct = round((p_cals / sum_cals) * 100)
        c_pct = round((c_cals / sum_cals) * 100)
        f_pct = max(0, 100 - (p_pct + c_pct))
        return {"protein_pct": p_pct, "carbs_pct": c_pct, "fat_pct": f_pct}


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

    def clean(self) -> None:
        """Validate that ingredient fields are free of expletives and hurtful language."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)

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
