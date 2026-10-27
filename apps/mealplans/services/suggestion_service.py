"""
Service layer for intelligent meal dish suggestions.

Ranks and suggests candidate recipes for a planned meal based on:
1. Meal Name & Historical Pairings:
   - Recipes frequently appearing in other meals with identical or similar names.
   - Name keyword semantics (e.g. 'Taco Tuesday', 'Sunday Brunch', 'Dinner', 'Lunch').
2. Dish Type Role & Course Completeness:
   - Identifying courses currently present (Main, Salad, Soup, Side, Dessert).
   - When a meal has soup, salad, or dessert without a main, prioritizes main dishes.
   - When a meal has a main dish, prioritizes complementary salads, sides, soups, desserts.
3. Nutritional Completeness & Macro Balance:
   - Calculating current calories, protein, and fiber of planned dishes in the meal.
   - Boosting dishes that fulfill protein gaps, dietary fiber, or caloric balance.
4. Extensible Rule Engine:
   - Evaluates active MealPlanRules (e.g. 'each dinner should have a vegetarian protein',
     'low carb', 'high protein', 'include salad').
   - Modular rule evaluator pattern allowing arbitrary future rules.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from apps.mealplans.models import Meal, MealPlanRule
from apps.recipes.models import Recipe


@dataclass
class DishSuggestion:
    """An individual ranked dish recommendation for a meal with explanatory reasons."""
    recipe: Recipe
    score: float
    reasons: list[str] = field(default_factory=list)
    rule_matches: list[str] = field(default_factory=list)
    role: str = "main"

    @property
    def primary_reason(self) -> str:
        """Return the most prominent recommendation reason."""
        return self.reasons[0] if self.reasons else "Great match for this meal"


# ---------------------------------------------------------------------------
# Dish Type Categorization
# ---------------------------------------------------------------------------

MAIN_KEYWORDS = (
    "main", "entree", "casserole", "stew", "pasta", "sandwich",
    "pizza", "curry", "roast", "burger", "taco", "tacos", "enchilada",
    "lasagna", "pie (savory)", "pot pie", "steak", "chicken", "beef", "pork",
)
SALAD_KEYWORDS = ("salad", "slaw")
SOUP_KEYWORDS = ("soup", "chowder", "bisque", "chili", "broth", "ramen")
SIDE_KEYWORDS = ("side", "vegetable", "grain", "rice", "beans", "bread", "rolls", "fries", "potato", "kale", "corn")
DESSERT_KEYWORDS = ("dessert", "baking", "sweet", "cake", "pie", "cookie", "cookies", "fudge", "ice cream", "pudding")
BREAKFAST_KEYWORDS = ("breakfast", "brunch", "pancake", "pancakes", "waffle", "waffles", "omelet", "hashbrown", "hashbrowns")


def get_recipe_role(recipe: Recipe) -> str:
    """
    Determine primary culinary course role:
    'main', 'salad', 'soup', 'side', 'dessert', 'breakfast', or 'other'.
    """
    dish_type_lower = (recipe.dish_type or "").lower()
    meal_type_str = " ".join(recipe.meal_type or []).lower()
    name_lower = recipe.name.lower()
    haystack = f"{dish_type_lower} {meal_type_str} {name_lower}"

    if any(k in haystack for k in SALAD_KEYWORDS):
        return "salad"
    if any(k in haystack for k in SOUP_KEYWORDS):
        if "main" in dish_type_lower:
            return "main"
        return "soup"
    if any(k in haystack for k in DESSERT_KEYWORDS):
        return "dessert"
    if any(k in haystack for k in BREAKFAST_KEYWORDS):
        return "breakfast"
    if any(k in haystack for k in SIDE_KEYWORDS):
        if "main" in dish_type_lower or "casserole" in dish_type_lower:
            return "main"
        return "side"
    if any(k in haystack for k in MAIN_KEYWORDS):
        return "main"
    if "dinner" in meal_type_str or "lunch" in meal_type_str:
        return "main"

    return "other"


# ---------------------------------------------------------------------------
# Extensible Rule Engine
# ---------------------------------------------------------------------------

RuleChecker = Callable[[str, Recipe, Meal], tuple[float, str | None]]


def check_vegetarian_protein_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """
    Handles rules such as 'each dinner should have a vegetarian protein' or 'veggie protein'.
    """
    rule_lower = rule_text.lower()
    if not (
        "vegetarian protein" in rule_lower
        or "veggie protein" in rule_lower
        or ("vegetarian" in rule_lower and "protein" in rule_lower)
    ):
        return 0.0, None

    dietary = [d.lower() for d in (candidate.dietary_restrictions or [])]
    is_veg = "vegetarian" in dietary or "vegan" in dietary

    has_high_protein = candidate.protein_per_serving_g >= Decimal("10.0")
    plant_protein_keywords = (
        "tofu", "beans", "lentils", "chickpeas", "edamame",
        "tempeh", "seitan", "egg", "eggs", "paneer", "nut", "nuts", "peanut", "chia", "soy",
    )
    has_plant_protein_ing = any(
        any(k in ing.name.lower() for k in plant_protein_keywords)
        for ing in candidate.ingredients.all()
    )

    if is_veg and (has_high_protein or has_plant_protein_ing):
        protein_str = f"{candidate.protein_per_serving_g:g}" if candidate.protein_per_serving_g > 0 else "plant"
        return 75.0, f"🥬 Fulfills rule: '{rule_text}' (+{protein_str}g plant protein)"
    elif not is_veg:
        return -50.0, None

    return 0.0, None


def check_general_vegetarian_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """Handles rules requiring vegetarian or vegan dishes."""
    rule_lower = rule_text.lower()
    if "vegetarian protein" in rule_lower or "veggie protein" in rule_lower:
        return 0.0, None  # Handled specifically by check_vegetarian_protein_rule

    dietary = [d.lower() for d in (candidate.dietary_restrictions or [])]
    is_veg = "vegetarian" in dietary or "vegan" in dietary

    if "vegan" in rule_lower:
        if "vegan" in dietary:
            return 50.0, f"🌱 Fulfills rule: '{rule_text}' (100% Vegan)"
        return -40.0, None

    if "vegetarian" in rule_lower:
        if is_veg:
            return 45.0, f"🌱 Fulfills rule: '{rule_text}' (Vegetarian)"
        return -40.0, None

    return 0.0, None


def check_high_protein_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """Handles rules requiring high protein dishes."""
    rule_lower = rule_text.lower()
    if "high protein" in rule_lower or "protein packed" in rule_lower:
        if candidate.protein_per_serving_g >= Decimal("20.0"):
            return 40.0, f"🍗 Fulfills rule: '{rule_text}' ({candidate.protein_per_serving_g:g}g protein)"
        elif candidate.protein_per_serving_g >= Decimal("12.0"):
            return 20.0, f"🍗 Good protein source ({candidate.protein_per_serving_g:g}g protein)"
    return 0.0, None


def check_low_carb_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """Handles low-carb / keto rules."""
    rule_lower = rule_text.lower()
    if "low carb" in rule_lower or "keto" in rule_lower:
        if candidate.carbs_per_serving_g > 0 and candidate.carbs_per_serving_g <= Decimal("15.0"):
            return 45.0, f"🥑 Fulfills rule: '{rule_text}' ({candidate.carbs_per_serving_g:g}g carbs)"
        elif candidate.carbs_per_serving_g > Decimal("30.0"):
            return -30.0, None
    return 0.0, None


def check_salad_vegetable_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """Handles rules requiring a salad or green vegetable."""
    rule_lower = rule_text.lower()
    if any(k in rule_lower for k in ("salad", "veggie", "vegetable", "greens")):
        role = get_recipe_role(candidate)
        if role in ("salad", "side"):
            return 45.0, f"🥗 Fulfills rule: '{rule_text}'"
    return 0.0, None


def check_generic_keyword_rule(rule_text: str, candidate: Recipe, meal: Meal) -> tuple[float, str | None]:
    """Handles keyword or cuisine rules (e.g. 'Mexican', 'Italian', 'Soup')."""
    rule_words = [w for w in rule_text.lower().split() if len(w) > 3 and w not in ("should", "every", "needs", "have", "with", "must")]
    cand_text = f"{candidate.name} {candidate.cuisine} {candidate.dish_type}".lower()
    for w in rule_words:
        if w in cand_text:
            return 30.0, f"🎯 Matches guideline: '{w.title()}'"
    return 0.0, None


# Modular rule registry
RULE_HANDLERS: list[RuleChecker] = [
    check_vegetarian_protein_rule,
    check_general_vegetarian_rule,
    check_high_protein_rule,
    check_low_carb_rule,
    check_salad_vegetable_rule,
    check_generic_keyword_rule,
]


def evaluate_rules_for_recipe(candidate: Recipe, meal: Meal, rules: list[MealPlanRule]) -> tuple[float, list[str]]:
    """Evaluate all active meal plan rules against a candidate recipe."""
    total_delta = 0.0
    matched_reasons = []

    for rule in rules:
        if not rule.is_active or not rule.rule_text.strip():
            continue
        for handler in RULE_HANDLERS:
            delta, reason = handler(rule.rule_text, candidate, meal)
            if delta != 0.0:
                total_delta += delta
                if reason and reason not in matched_reasons:
                    matched_reasons.append(reason)
                break  # Matched primary handler for this rule

    return total_delta, matched_reasons


# ---------------------------------------------------------------------------
# Core Suggestion Scoring Function
# ---------------------------------------------------------------------------

def calculate_current_meal_nutrition(meal: Meal) -> dict[str, Any]:
    """Compute aggregate nutritional values for dishes currently planned in meal."""
    cals = 0
    protein = Decimal("0.0")
    carbs = Decimal("0.0")
    fat = Decimal("0.0")
    fiber = Decimal("0.0")

    for dish in meal.dishes_list:
        r = dish.recipe
        scale = dish.scale_factor or Decimal("1.00")
        cals += int(r.calories_per_serving * scale)
        protein += Decimal(str(r.protein_per_serving_g)) * scale
        carbs += Decimal(str(r.carbs_per_serving_g)) * scale
        fat += Decimal(str(r.fat_per_serving_g)) * scale
        fiber += Decimal(str(r.fiber_per_serving_g)) * scale

    return {
        "calories": cals,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "fiber": fiber,
    }


def get_dish_suggestions(meal: Meal, limit: int = 4) -> list[DishSuggestion]:
    """
    Generate ranked dish recommendations to add to the given meal.

    Args:
        meal: Target Meal instance.
        limit: Maximum number of suggestions to return (default: 4).

    Returns:
        List of DishSuggestion objects ordered from highest to lowest recommendation score.
    """
    # 1. Planned recipes to exclude
    existing_recipe_ids = set(meal.recipes.values_list("id", flat=True))

    candidate_recipes = (
        Recipe.objects.exclude(id__in=existing_recipe_ids)
        .prefetch_related("ingredients")
        .all()
    )
    if not candidate_recipes.exists():
        return []

    # 2. Analyze current meal state
    current_recipes = list(meal.recipes.all())
    current_roles = {get_recipe_role(r) for r in current_recipes}
    has_main = "main" in current_roles
    has_salad = "salad" in current_roles
    has_soup = "soup" in current_roles
    has_side = "side" in current_roles
    has_dessert = "dessert" in current_roles

    meal_name_lower = meal.name.lower()
    is_dinner_or_lunch = any(k in meal_name_lower for k in ("dinner", "supper", "lunch"))
    is_breakfast = any(k in meal_name_lower for k in ("breakfast", "brunch", "morning"))

    # 3. Analyze current nutrition
    current_nutrition = calculate_current_meal_nutrition(meal)
    current_cals = current_nutrition["calories"]
    current_protein = current_nutrition["protein"]
    current_fiber = current_nutrition["fiber"]

    # 4. Historical pairings from other meals with matching name
    historical_meals = (
        Meal.objects.filter(name__iexact=meal.name)
        .exclude(id=meal.id)
        .prefetch_related("recipes")
    )
    historical_recipe_counts: dict[int, int] = {}
    for h_meal in historical_meals:
        for h_recipe in h_meal.recipes.all():
            historical_recipe_counts[h_recipe.id] = historical_recipe_counts.get(h_recipe.id, 0) + 1

    # 5. Fetch active guidelines/rules
    active_rules = list(meal.meal_plan.rules.filter(is_active=True)) if meal.meal_plan_id else []

    scored_suggestions: list[DishSuggestion] = []

    for candidate in candidate_recipes:
        score = 0.0
        reasons: list[str] = []
        rule_matches: list[str] = []
        candidate_role = get_recipe_role(candidate)

        # ---------------------------------------------------------
        # Course Complementarity Logic
        # (e.g. Dinner has salad, soup, dessert -> suggest main dish)
        # ---------------------------------------------------------
        if not has_main:
            if candidate_role == "main":
                if current_recipes:
                    score += 65.0
                    reasons.append("🍖 Adds a hearty main dish to complete your meal")
                elif is_dinner_or_lunch:
                    score += 45.0
                    reasons.append("🍽️ Centerpiece main dish for dinner")
                else:
                    score += 35.0
                    reasons.append("🍽️ Substantial centerpiece dish")
            elif is_breakfast and candidate_role in ("breakfast", "main"):
                score += 40.0
                reasons.append("🥞 Ideal breakfast centerpiece")
        else:
            # Main dish already present: prioritize complementary courses
            if not has_salad and candidate_role == "salad":
                score += 35.0
                reasons.append("🥗 Complements your main with a fresh salad")
            elif not has_side and candidate_role == "side":
                score += 30.0
                reasons.append("🥦 Complements with a healthy vegetable side")
            elif not has_soup and candidate_role == "soup":
                score += 25.0
                reasons.append("🍲 Adds a warming soup accompaniment")
            elif not has_dessert and candidate_role == "dessert" and (is_dinner_or_lunch or not current_roles):
                score += 20.0
                reasons.append("🍰 Sweet dessert finish for the meal")
            elif candidate_role == "main":
                score -= 20.0  # Meal already has a main dish

        # ---------------------------------------------------------
        # Historical Pairing Logic
        # ---------------------------------------------------------
        if candidate.id in historical_recipe_counts:
            freq = historical_recipe_counts[candidate.id]
            score += min(freq * 25.0, 50.0)
            reasons.append(f"⭐ Often enjoyed in '{meal.name}'")

        # Meal name theme keyword matches
        if "taco" in meal_name_lower and any(k in candidate.name.lower() or k in (candidate.cuisine or "").lower() for k in ("taco", "mexican", "salsa")):
            score += 30.0
            reasons.append("🌮 Matches Taco theme")
        elif any(k in meal_name_lower for k in ("italian", "pizza", "pasta")) and ("italian" in (candidate.cuisine or "").lower() or "pasta" in candidate.name.lower()):
            score += 30.0
            reasons.append("🍝 Matches Italian theme")

        # ---------------------------------------------------------
        # Nutritional Completeness & Balance
        # ---------------------------------------------------------
        if current_protein < Decimal("15.0"):
            if candidate.protein_per_serving_g >= Decimal("15.0"):
                score += min(float(candidate.protein_per_serving_g) * 1.5, 45.0)
                reasons.append(f"💪 Fills protein gap (+{candidate.protein_per_serving_g:g}g protein)")
        elif current_protein >= Decimal("35.0") and candidate.protein_per_serving_g >= Decimal("30.0"):
            score -= 10.0  # Meal already has excessive protein; encourage balance

        if current_fiber < Decimal("4.0"):
            if candidate.fiber_per_serving_g >= Decimal("3.0"):
                score += min(float(candidate.fiber_per_serving_g) * 2.5, 30.0)
                reasons.append(f"🥑 Adds dietary fiber (+{candidate.fiber_per_serving_g:g}g fiber)")

        if current_cals > 650:
            if candidate.calories_per_serving > 0 and candidate.calories_per_serving < 250:
                score += 20.0
                reasons.append("🌿 Light, nutrient-dense complement")
            elif candidate.calories_per_serving > 500:
                score -= 15.0  # Avoid overly heavy add-ons
        elif current_cals < 250 and 300 <= candidate.calories_per_serving <= 700:
            score += 15.0

        # ---------------------------------------------------------
        # Rule Engine Evaluation
        # ---------------------------------------------------------
        rule_delta, matches = evaluate_rules_for_recipe(candidate, meal, active_rules)
        score += rule_delta
        if matches:
            rule_matches.extend(matches)
            # Insert rule reasons at the beginning of the reasons list for maximum visibility
            reasons = matches + reasons

        # Baseline popular / tested bonus
        if candidate.times_made > 0:
            score += min(candidate.times_made * 2.0, 10.0)

        # Deduplicate reasons while preserving order
        deduped_reasons: list[str] = []
        for r in reasons:
            if r not in deduped_reasons:
                deduped_reasons.append(r)

        scored_suggestions.append(
            DishSuggestion(
                recipe=candidate,
                score=score,
                reasons=deduped_reasons[:3],
                rule_matches=rule_matches,
                role=candidate_role,
            )
        )

    # Sort descending by score
    scored_suggestions.sort(key=lambda s: s.score, reverse=True)
    return scored_suggestions[:limit]
