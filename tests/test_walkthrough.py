"""
Tests for the first-time user walkthrough overlay, avatar menu integration,
and auto-launch session context processor.
"""

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.core.context_processors import workspace_context

User = get_user_model()


@pytest.mark.django_db
def test_walkthrough_modal_content_renders():
    """Verify walkthrough overlay renders all tutorial steps with unblurred spotlight and informational text."""
    html = render_to_string("core/partials/walkthrough_modal.html")

    # Verify all tutorial steps are present
    assert "Shopping list with real-time transitions" in html
    assert "the list updates in real time via Websockets" in html
    assert "Sorting by priority and store aisle" in html
    assert "Pantry check" in html
    assert "Search and filter recipes" in html
    assert "Import from a URL or create a recipe" in html
    assert "Organize with workspaces" in html
    assert "Preset lists and recurring schedules" in html

    # Verify unblurred spotlight quadrants & green spotlight border
    assert 'id="walkthrough-modal"' in html
    assert 'id="tour-backdrop-top"' in html
    assert 'id="tour-backdrop-bottom"' in html
    assert 'id="tour-backdrop-left"' in html
    assert 'id="tour-backdrop-right"' in html
    assert 'id="tour-spotlight-border"' in html
    assert 'id="tour-tooltip-card"' in html
    assert "openWalkthroughModal" in html
    assert "closeWalkthroughModal" in html
    assert "goToTourStep" in html
    assert "positionSpotlightAndTooltip" in html
    assert "tourStepConfigs" in html


@pytest.mark.django_db
def test_tour_navigation_tab_destinations_and_elements(db):
    """Verify that pages referenced by the tour contain valid target elements."""
    user = User.objects.create_user(username="tourcheck", password="password123")
    client = Client()
    client.force_login(user)

    # 1. Recipes page has recipe-filter-form and recipe-action-buttons
    recipes_res = client.get(reverse("recipes:list"))
    assert recipes_res.status_code == 200
    recipes_html = recipes_res.content.decode("utf-8")
    assert 'id="recipe-filter-form"' in recipes_html
    assert 'id="recipe-action-buttons"' in recipes_html

    # 2. Preset lists page has preset grid container
    presets_res = client.get(reverse("shopping:preset_list_index"))
    assert presets_res.status_code == 200
    presets_html = presets_res.content.decode("utf-8")
    assert 'id="preset-index-grid-container"' in presets_html

    # 3. Pantry Check page renders pantry check mode
    pantry_res = client.get(reverse("shopping:pantry_check"))
    assert pantry_res.status_code == 200
    pantry_html = pantry_res.content.decode("utf-8")
    assert 'id="shopping-list-content"' in pantry_html


@pytest.mark.django_db
def test_avatar_menu_contains_product_tour_item(db):
    """Verify that logged in user avatar menu contains the Product Tour button."""
    user = User.objects.create_user(username="testtourist", password="password123")
    client = Client()
    client.force_login(user)

    response = client.get(reverse("recipes:list"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Product Tour" in content
    assert "startProductTour()" in content


@pytest.mark.django_db
def test_workspace_context_pops_auto_launch_tour():
    """Verify that workspace_context delivers auto_launch_tour once and pops it from session."""
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {"auto_launch_tour": True}
    request.user = User.objects.create_user(username="ctxuser", password="password123")

    # First call receives True and removes it from session
    ctx1 = workspace_context(request)
    assert ctx1["auto_launch_tour"] is True
    assert "auto_launch_tour" not in request.session

    # Second call receives False
    ctx2 = workspace_context(request)
    assert ctx2["auto_launch_tour"] is False
