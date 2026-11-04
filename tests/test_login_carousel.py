"""
Tests for login page recipe carousel, guest recipe exploration,
and first-time login auto-launch tour detection.
"""


import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.recipes.models import Recipe
from apps.recipes.services.recipe_service import get_featured_carousel_recipes

User = get_user_model()


@pytest.fixture
def carousel_recipes(db):
    user = User.objects.create_user(username="chef", password="password123")

    # 1. Public, approved, has photo_urls
    r1 = Recipe.objects.create(
        name="Crêpes",
        description="A simple and versatile crêpes recipe",
        cuisine="French",
        dish_type="Dessert",
        photo_urls=["/media/recipes/photos/crepes.jpg"],
        is_public=True,
        is_approved=True,
        created_by=user,
    )

    # 2. Public, approved, has photo_urls
    r2 = Recipe.objects.create(
        name="Lasagna",
        description="Classic Italian-American casserole",
        cuisine="Italian",
        dish_type="Casserole",
        photo_urls=["/media/recipes/photos/lasagna.jpg"],
        is_public=True,
        is_approved=True,
        created_by=user,
    )

    # 3. Public, approved, NO photos
    Recipe.objects.create(
        name="Plain Rice",
        description="No photo attached",
        photo_urls=[],
        is_public=True,
        is_approved=True,
        created_by=user,
    )

    # 4. Private recipe with photo
    Recipe.objects.create(
        name="Private Stew",
        description="Secret recipe",
        photo_urls=["/media/recipes/photos/stew.jpg"],
        is_public=False,
        is_approved=True,
        created_by=user,
    )

    # 5. Unapproved recipe with photo
    Recipe.objects.create(
        name="Unapproved Cake",
        description="Pending review",
        photo_urls=["/media/recipes/photos/cake.jpg"],
        is_public=True,
        is_approved=False,
        created_by=user,
    )

    return r1, r2


@pytest.mark.django_db
def test_get_featured_carousel_recipes(carousel_recipes):
    """Ensure get_featured_carousel_recipes only includes public, approved recipes with photos."""
    r1, r2 = carousel_recipes
    featured = get_featured_carousel_recipes(limit=10)
    featured_names = [r.name for r in featured]

    assert "Crêpes" in featured_names
    assert "Lasagna" in featured_names
    assert "Plain Rice" not in featured_names
    assert "Private Stew" not in featured_names
    assert "Unapproved Cake" not in featured_names


@pytest.mark.django_db
def test_login_page_renders_carousel_and_guest_browse(carousel_recipes):
    """Test that login page shows carousel, exact recipe titles, and guest browsing link."""
    client = Client()
    response = client.get(reverse("core:login"))
    assert response.status_code == 200

    content = response.content.decode("utf-8")
    assert "Browse recipes, manage shopping lists, and plan meals" in content
    assert "Browse Recipes (No Login Required)" in content
    assert "Free to use" in content
    assert "No ads" in content
    assert "Recipes with Photos" not in content
    assert "Auto-advances every 5 seconds" not in content
    assert "Crêpes" in content
    assert "Lasagna" in content
    assert "featured_recipes" in response.context
    assert len(response.context["featured_recipes"]) >= 2


@pytest.mark.django_db
def test_first_time_login_sets_auto_launch_tour(db):
    """Test that first-time login (last_login is None) sets auto_launch_tour session flag."""
    User.objects.create_user(username="newuser", password="password123")
    user = User.objects.get(username="newuser")
    assert user.last_login is None

    client = Client()
    response = client.post(
        reverse("core:login"),
        {"username": "newuser", "password": "password123"},
    )
    assert response.status_code == 302
    assert client.session.get("auto_launch_tour") is True


@pytest.mark.django_db
def test_repeat_login_does_not_set_auto_launch_tour(db):
    """Test that repeat login (last_login already populated) does not set auto_launch_tour."""
    from django.utils import timezone

    user = User.objects.create_user(username="returninguser", password="password123")
    user.last_login = timezone.now()
    user.save()

    client = Client()
    response = client.post(
        reverse("core:login"),
        {"username": "returninguser", "password": "password123"},
    )
    assert response.status_code == 302
    assert client.session.get("auto_launch_tour") is not True


@pytest.mark.django_db
def test_guest_can_access_recipe_detail_from_login_carousel(carousel_recipes):
    """Ensure guests can navigate directly to a recipe detail page without logging in."""
    r1, _ = carousel_recipes
    client = Client()
    response = client.get(r1.get_absolute_url())
    assert response.status_code == 200
    assert "Crêpes" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_login_page_upper_right_signin_button(carousel_recipes):
    """Test that on the login page, the upper right Sign In button targets #sign-in-card and does not reload."""
    client = Client()
    response = client.get(reverse("core:login"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    # Sign in card has proper ID and scroll offset
    assert 'id="sign-in-card"' in content
    # Header Sign In button uses hash anchor and smooth scroll handler on the login page
    assert 'href="#sign-in-card"' in content
    assert 'onclick="scrollToSignIn(event)"' in content
    # Should not link to itself with a circular next query param
    assert 'next=/core/login' not in content
    assert 'next=/login' not in content

    # On recipe list, guest sign-in button links to login view with next param
    recipes_response = client.get(reverse("recipes:list"))
    recipes_content = recipes_response.content.decode("utf-8")
    assert f'href="{reverse("core:login")}?next={reverse("recipes:list")}"' in recipes_content


@pytest.mark.django_db
def test_login_next_url_sanitization():
    """Ensure disallowed login/logout next urls are sanitized to prevent loops."""
    client = Client()
    response = client.get(f"{reverse('core:login')}?next=/login/")
    assert response.status_code == 200
    assert response.context["next"] == ""

