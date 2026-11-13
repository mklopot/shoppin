"""
Tests for Google OAuth, guest browsing, moderation filtering,
and straightforward recipe slug URLs.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.recipes.models import Ingredient, Recipe

User = get_user_model()


@pytest.fixture
def test_recipes(db, auth_user):
    user, _ = auth_user

    public_approved = Recipe.objects.create(
        name="Delicious Blueberry Scones",
        description="Flaky and buttery scones packed with fresh blueberries.",
        directions="1. Mix dry ingredients.\n2. Cut in butter.\n3. Fold in berries.\n4. Bake at 400F.",
        cuisine="British",
        dish_type="Dessert",
        difficulty_level="easy",
        portions=8,
        prep_time_minutes=20,
        cook_time_minutes=15,
        is_public=True,
        is_approved=True,
        created_by=user,
    )
    Ingredient.objects.create(
        recipe=public_approved,
        name="Flour",
        amount=Decimal("2.5"),
        amount_unit="cup",
        order=0,
    )

    private_unapproved = Recipe.objects.create(
        name="Secret Family Chili",
        description="A top secret chili recipe pending moderation review.",
        directions="1. Simmer beef and beans for 4 hours.",
        cuisine="American",
        dish_type="Stew",
        difficulty_level="medium",
        portions=6,
        prep_time_minutes=15,
        cook_time_minutes=240,
        is_public=False,
        is_approved=False,
        created_by=user,
    )

    return public_approved, private_unapproved


# ---------------------------------------------------------------------------
# Slug URLs & Absolute URL
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recipe_slug_generation_and_absolute_url(test_recipes):
    public_recipe, _ = test_recipes
    assert public_recipe.slug == "delicious-blueberry-scones"
    assert public_recipe.get_absolute_url() == "/recipes/delicious-blueberry-scones/"


# ---------------------------------------------------------------------------
# Guest Access to Public Approved Recipes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_can_view_public_approved_recipe_by_slug(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:detail_slug", kwargs={"slug": public_recipe.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert "Delicious Blueberry Scones" in response.content.decode()
    assert "Sign in with Google" in response.content.decode()


@pytest.mark.django_db
def test_guest_can_view_public_approved_recipe_by_id(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:detail", kwargs={"recipe_id": public_recipe.id})
    response = client.get(url)
    assert response.status_code == 200
    assert "Delicious Blueberry Scones" in response.content.decode()


@pytest.mark.django_db
def test_guest_can_view_public_recipe_list(client: Client, test_recipes):
    public_recipe, private_recipe = test_recipes
    response = client.get(reverse("recipes:list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert public_recipe.name in content
    # Private / unapproved recipe should not appear for unauthenticated guest
    assert private_recipe.name not in content


# ---------------------------------------------------------------------------
# Moderation & Private Access Control
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_accessing_unapproved_recipe_redirects_to_login(client: Client, test_recipes):
    _, private_recipe = test_recipes
    url = reverse("recipes:detail_slug", kwargs={"slug": private_recipe.slug})
    response = client.get(url)
    # Guest should be redirected to login with next param
    assert response.status_code == 302
    assert reverse("core:login") in response.url
    assert f"next={url}" in response.url


@pytest.mark.django_db
def test_non_owner_user_cannot_view_unapproved_recipe(client: Client, test_recipes):
    _, private_recipe = test_recipes
    # Create another regular user
    other_user = User.objects.create_user(username="other_guest", password="password123")
    client.force_login(other_user)

    url = reverse("recipes:detail_slug", kwargs={"slug": private_recipe.slug})
    response = client.get(url)
    assert response.status_code == 403


@pytest.mark.django_db
def test_creator_can_view_own_unapproved_recipe(client: Client, auth_user, test_recipes):
    user, _ = auth_user
    _, private_recipe = test_recipes
    client.force_login(user)

    url = reverse("recipes:detail_slug", kwargs={"slug": private_recipe.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert "Secret Family Chili" in response.content.decode()


@pytest.mark.django_db
def test_staff_can_view_any_unapproved_recipe(client: Client, test_recipes):
    _, private_recipe = test_recipes
    staff_user = User.objects.create_user(username="mod_admin", password="password123", is_staff=True)
    client.force_login(staff_user)

    url = reverse("recipes:detail_slug", kwargs={"slug": private_recipe.slug})
    response = client.get(url)
    assert response.status_code == 200
    assert "Secret Family Chili" in response.content.decode()


# ---------------------------------------------------------------------------
# Protected Recipe Mutations require Auth
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_creating_recipe_redirects_to_login(client: Client):
    response = client.get(reverse("recipes:create"))
    assert response.status_code == 302
    assert reverse("core:login") in response.url


@pytest.mark.django_db
def test_guest_importing_url_redirects_to_login(client: Client):
    response = client.post(reverse("recipes:import_url"), {"url": "https://example.com/recipe"})
    assert response.status_code == 302
    assert reverse("core:login") in response.url


@pytest.mark.django_db
def test_guest_editing_recipe_redirects_to_login(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:edit_slug", kwargs={"slug": public_recipe.slug})
    response = client.get(url)
    assert response.status_code == 302
    assert reverse("core:login") in response.url


@pytest.mark.django_db
def test_guest_deleting_recipe_forbidden(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:delete_slug", kwargs={"slug": public_recipe.slug})
    response = client.post(url)
    assert response.status_code == 403


@pytest.mark.django_db
def test_guest_rating_recipe_forbidden(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:rate_slug", kwargs={"slug": public_recipe.slug})
    response = client.post(url, {"stars": 5, "thumbs_up": "1"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_guest_adding_to_mealplan_forbidden(client: Client, test_recipes):
    public_recipe, _ = test_recipes
    url = reverse("recipes:add_to_mealplan_slug", kwargs={"slug": public_recipe.slug})
    response = client.post(url, {"meal_name": "Tonight"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Auth Views (Login, Logout, Dev switchers)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_page_renders(client: Client):
    response = client.get(reverse("core:login"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Sign in with Google" in content
    assert "Browse published recipes as Guest" in content


@pytest.mark.django_db
def test_logout_redirects_and_sets_guest_mode(client: Client, auth_user):
    user, _ = auth_user
    client.force_login(user)

    response = client.post(reverse("core:logout"))
    assert response.status_code == 302
    # Verify session has guest_mode = True
    session = client.session
    assert session.get("guest_mode") is True


@pytest.mark.django_db
def test_session_retention_defaults_to_one_year(client: Client, auth_user, settings):
    """Verify session expiry is configured for 1 full year by default (31,536,000 seconds)."""
    assert settings.SESSION_COOKIE_AGE == 60 * 60 * 24 * 365
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
    assert settings.SESSION_SAVE_EVERY_REQUEST is True

    user, _ = auth_user
    client.login(username=user.username, password="password123")
    # Verify session cookie age
    session = client.session
    assert session.get_expiry_age() == 60 * 60 * 24 * 365


# ---------------------------------------------------------------------------
# Google OAuth Flow (Mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_google_login_view_redirects_to_google_oauth(client: Client, settings):
    settings.GOOGLE_CLIENT_ID = "mock-client-id.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "mock-client-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:8000/accounts/google/callback/"

    response = client.get(reverse("core:google_login"))
    assert response.status_code == 302
    assert "accounts.google.com/o/oauth2/v2/auth" in response.url
    assert "client_id=mock-client-id.apps.googleusercontent.com" in response.url
    # Verify CSRF state is stored in session
    assert "oauth_state" in client.session


@pytest.mark.django_db
def test_google_callback_rejects_state_mismatch(client: Client):
    session = client.session
    session["oauth_state"] = "valid-state-123"
    session.save()

    callback_url = f"{reverse('core:google_callback')}?state=tampered-state&code=test-auth-code"
    response = client.get(callback_url)
    assert response.status_code == 302
    assert reverse("core:login") in response.url


@pytest.mark.django_db
@patch("apps.core.services.oauth_service.requests.post")
@patch("apps.core.services.oauth_service.requests.get")
def test_google_callback_success_creates_user_and_workspace(
    mock_get,
    mock_post,
    client: Client,
    settings,
):
    settings.GOOGLE_CLIENT_ID = "mock-client-id"
    settings.GOOGLE_CLIENT_SECRET = "mock-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:8000/accounts/google/callback/"

    # Mock token exchange
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "mock-access-token",
        "token_type": "Bearer",
    }
    mock_post.return_value = token_response

    # Mock userinfo endpoint
    userinfo_response = MagicMock()
    userinfo_response.status_code = 200
    userinfo_response.json.return_value = {
        "email": "newchef@example.com",
        "name": "Chef Auguste",
        "given_name": "Auguste",
        "family_name": "Escoffier",
        "picture": "https://example.com/avatar.jpg",
    }
    mock_get.return_value = userinfo_response

    # Setup session with matching state
    session = client.session
    session["oauth_state"] = "csrf-token-abc"
    session["oauth_next"] = "/recipes/"
    session.save()

    callback_url = f"{reverse('core:google_callback')}?state=csrf-token-abc&code=auth-code-xyz"
    response = client.get(callback_url)

    # Should redirect new user to terms acceptance gate before target
    assert response.status_code == 302
    assert response.url == f"{reverse('core:terms_accept')}?next=/recipes/"

    # Verify user was created
    created_user = User.objects.get(email="newchef@example.com")
    assert created_user.first_name == "Auguste"
    assert created_user.last_name == "Escoffier"

    # Verify workspace was created for user
    ws = created_user.owned_workspaces.first()
    assert ws is not None
    assert "Auguste" in ws.name
    assert ws.owner == created_user
