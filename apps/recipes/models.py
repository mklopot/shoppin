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
    is_web_imported = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this recipe was created or pre-filled from an external web URL",
    )
    copyright_cleared = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Verified by an administrator as sufficiently re-worded and non-infringing for public sharing",
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

    # Workspace Associations
    shared_workspaces = models.ManyToManyField(
        "core.Workspace",
        blank=True,
        related_name="associated_recipes",
        help_text="Workspaces where this recipe is accessible and eligible for meal planning.",
    )
    last_shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shared_recipes",
        help_text="User who most recently shared or copied this recipe into a workspace",
    )

    # Provenance & Version Lineage
    forked_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forks",
        help_text="Immediate recipe this was copied/modified from",
    )
    forked_from_title = models.CharField(max_length=255, blank=True)
    forked_from_author_name = models.CharField(max_length=255, blank=True)

    root_recipe = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="all_descendants",
        help_text="The ultimate original root recipe in the provenance chain",
    )
    original_author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="original_recipes_seeded",
    )
    original_author_name = models.CharField(max_length=255, blank=True)
    original_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def clean(self) -> None:
        """Validate recipe content, expletives, moderation, and public status permissions."""
        super().clean()
        from apps.core.services.moderation_service import check_model_instance_for_moderation
        check_model_instance_for_moderation(self)
        if self.is_web_imported and not self.copyright_cleared and self.is_public:
            from django.core.exceptions import ValidationError
            raise ValidationError(
                "Web-imported recipes cannot be made public until verified as re-worded and non-infringing by an administrator."
            )

    @property
    def is_locked_from_public(self) -> bool:
        """Return True if this recipe cannot be made public without admin copyright clearance."""
        return bool(self.is_web_imported and not self.copyright_cleared)

    def can_be_made_public(self, user=None) -> bool:
        """
        Check if this recipe can be made public, taking user permissions into account.
        Regular users cannot make web-imported recipes public unless copyright is cleared.
        Staff and superusers can override and make recipes public.
        """
        if not self.is_web_imported or self.copyright_cleared:
            return True
        if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
            return True
        return False

    def save(self, *args, **kwargs) -> None:
        """Auto-populate URL slug from name if not specified, ensure uniqueness, and maintain provenance metadata."""
        is_new = self.pk is None
        if not self.slug:
            base_slug = slugify(self.name) or "recipe"
            slug = base_slug
            counter = 1
            while Recipe.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Seed original author snapshot if original root recipe
        if not self.forked_from_id and not self.original_author_name and self.created_by:
            self.original_author = self.original_author or self.created_by
            self.original_author_name = self.created_by.get_full_name() or self.created_by.username

        super().save(*args, **kwargs)

        # Set root_recipe to self if original root and not already linked
        if is_new and not self.forked_from_id and not self.root_recipe_id:
            Recipe.objects.filter(pk=self.pk).update(root_recipe=self)
            self.root_recipe = self

    def __str__(self) -> str:
        """Return the recipe title."""
        return self.name

    def get_absolute_url(self) -> str:
        """Return straightforward public URL for this recipe."""
        if self.slug:
            return reverse("recipes:detail_slug", kwargs={"slug": self.slug})
        return reverse("recipes:detail", kwargs={"recipe_id": self.id})

    @property
    def original_author_display(self) -> str:
        """Display name of original author, falling back through root and snapshot fields."""
        if self.original_author:
            name = self.original_author.get_full_name() or self.original_author.username
            if name:
                return name
        if self.original_author_name:
            return self.original_author_name
        if self.root_recipe and self.root_recipe.created_by:
            name = self.root_recipe.created_by.get_full_name() or self.root_recipe.created_by.username
            if name:
                return name
        if self.created_by:
            return self.created_by.get_full_name() or self.created_by.username
        return "Community Cook"

    @property
    def original_date(self):
        """Date of original recipe creation."""
        if self.original_created_at:
            return self.original_created_at
        if self.root_recipe and self.root_recipe.created_at:
            return self.root_recipe.created_at
        return self.created_at

    def get_provenance_chain(self) -> list[dict]:
        """
        Traverse up the forked_from chain to return the full ancestry of this recipe.
        Safely prevents cycles and falls back to snapshot fields if parent records were deleted.
        """
        chain: list[dict] = []
        current: Recipe | None = self
        visited_ids: set[int] = set()

        while current:
            if current.id in visited_ids:
                break
            visited_ids.add(current.id)

            author_name = "Community Cook"
            if current.created_by:
                author_name = current.created_by.get_full_name() or current.created_by.username
            elif current.original_author_name:
                author_name = current.original_author_name

            chain.append({
                "recipe": current,
                "name": current.name,
                "author": author_name,
                "author_id": current.created_by_id,
                "created_at": current.created_at,
                "is_current": (current.id == self.id),
                "slug": current.slug,
            })

            parent = current.forked_from
            if not parent and current.forked_from_title:
                # Historical snapshot fallback
                chain.append({
                    "recipe": None,
                    "name": current.forked_from_title,
                    "author": current.forked_from_author_name or "Original Chef",
                    "author_id": None,
                    "created_at": None,
                    "is_current": False,
                    "slug": None,
                })
                break
            current = parent

        # If chain only has self, but root_recipe is different from self
        if len(chain) == 1 and self.root_recipe_id and self.root_recipe_id != self.id:
            root = self.root_recipe
            root_author = "Community Cook"
            if root and root.created_by:
                root_author = root.created_by.get_full_name() or root.created_by.username
            elif self.original_author_name:
                root_author = self.original_author_name
            if root:
                chain.append({
                    "recipe": root,
                    "name": root.name,
                    "author": root_author,
                    "author_id": root.created_by_id,
                    "created_at": root.created_at,
                    "is_current": False,
                    "slug": root.slug,
                })

        return chain

    def get_related_workspace_versions(self, workspace) -> models.QuerySet:
        """
        Find all other recipes in the same workspace that share the same root ancestor.
        """
        if not workspace:
            return Recipe.objects.none()
        root_id = self.root_recipe_id or self.id
        return Recipe.objects.filter(
            shared_workspaces=workspace
        ).filter(
            models.Q(root_recipe_id=root_id) | models.Q(id=root_id)
        ).exclude(id=self.id).distinct().order_by("name")

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
