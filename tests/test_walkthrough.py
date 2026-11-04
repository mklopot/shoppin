"""
Tests for the first-time user walkthrough modal, avatar menu integration,
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
    """Verify walkthrough modal partial renders all 6 steps with approved text."""
    html = render_to_string("core/partials/walkthrough_modal.html")

    # Verify all 6 steps are present
    assert "Search and filter recipes" in html
    assert "Import from a URL or create a recipe" in html
    assert "Organize with workspaces" in html
    assert "Shopping list with store aisle sorting" in html
    assert "the list updates in real time via Websockets" in html
    assert "Pantry check" in html
    assert "Preset lists and recurring schedules" in html

    # Verify modal controls
    assert 'id="walkthrough-modal"' in html
    assert "openWalkthroughModal" in html
    assert "closeWalkthroughModal" in html
    assert "goToWalkthroughStep" in html


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
    assert "openWalkthroughModal()" in content


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
