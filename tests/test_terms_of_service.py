"""
Tests for Terms of Service: public viewing, mandatory acceptance gate,
client telemetry ingestion, and enforcement middleware.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.core.models import TermsOfServiceAcceptance
from apps.core.services.tos_service import has_user_accepted_latest_tos

User = get_user_model()


@pytest.fixture
def normal_user(db):
    return User.objects.create_user(
        username="culinary_user",
        email="culinary@example.com",
        password="secret_password_123",
    )


# ---------------------------------------------------------------------------
# Public Viewing of Draconian Terms
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_can_view_terms_of_service(client: Client):
    """Guest can access /terms/ and see the draconian terms and live telemetry detector."""
    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()

    # Check key draconian terms clauses
    assert "Shoppin Universal Terms of Service & Surrender of Rights" in content
    assert "PERPETUAL, UNIVERSE-WIDE ASSIGNMENT OF ALL CULINARY INTELLECTUAL PROPERTY" in content
    assert "ONE UNITED STATES CENT ($0.01)" in content
    assert "Ushuaia, Tierra del Fuego" in content
    assert "Ancient Sumerian" in content
    assert "Comprehensive Real-Time Client Telemetry Ingestion" in content

    # Guest should see prompt to sign in to execute terms
    assert "Sign in to Execute Terms" in content


@pytest.mark.django_db
def test_authenticated_user_without_acceptance_sees_acceptance_form(client: Client, normal_user):
    """Authenticated user who hasn't accepted yet sees the mandatory agreement form."""
    client.force_login(normal_user)
    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()

    assert "affirmative_surrender" in content
    assert "I IRREVOCABLY ACCEPT ALL TERMS & SURRENDER MY RIGHTS" in content


# ---------------------------------------------------------------------------
# Acceptance Execution & Telemetry Recording
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_terms_acceptance_fails_without_affirmative_checkbox(client: Client, normal_user):
    """POSTing without checking the affirmative surrender box is rejected."""
    client.force_login(normal_user)
    response = client.post(reverse("core:terms_accept"), {"next": "/recipes/"})
    assert response.status_code == 302
    assert reverse("core:terms_accept") in response.url
    assert not TermsOfServiceAcceptance.objects.filter(user=normal_user).exists()


@pytest.mark.django_db
def test_terms_acceptance_records_full_telemetry(client: Client, normal_user):
    """
    POSTing with agreement records all client-reported hardware, display,
    and network headers into the database.
    """
    client.force_login(normal_user)

    telemetry_payload = {
        "affirmative_surrender": "1",
        "next": "/recipes/",
        "screen_resolution": "2560x1440",
        "viewport_size": "2560x1380",
        "color_depth": "24-bit",
        "pixel_ratio": "2.0",
        "timezone": "America/New_York",
        "client_language": "en-US",
        "platform": "MacIntel",
        "hardware_concurrency": "16",
        "device_memory_gb": "16 GB",
        "touch_support": "true",
        "client_geolocation": "New York, NY, US",
        "raw_client_telemetry": '{"screen":{"width":2560},"network":{"effectiveType":"4g"}}',
    }

    # Simulate realistic proxy headers
    headers = {
        "HTTP_CF_CONNECTING_IP": "198.51.100.77",
        "HTTP_USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "HTTP_CF_IPCOUNTRY": "US",
        "HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9",
        "REMOTE_ADDR": "127.0.0.1",
    }

    response = client.post(reverse("core:terms_accept"), telemetry_payload, **headers)
    assert response.status_code == 302
    assert response.url == "/recipes/"

    # Verify audit record in database
    acceptance = TermsOfServiceAcceptance.objects.filter(user=normal_user).first()
    assert acceptance is not None
    assert acceptance.version == TermsOfServiceAcceptance.CURRENT_VERSION
    assert acceptance.ip_address == "198.51.100.77"
    assert "Macintosh" in acceptance.user_agent
    assert acceptance.geolocation == "New York, NY, US"
    assert acceptance.screen_resolution == "2560x1440"
    assert acceptance.viewport_size == "2560x1380"
    assert acceptance.color_depth == "24-bit"
    assert acceptance.pixel_ratio == "2.0"
    assert acceptance.timezone == "America/New_York"
    assert acceptance.client_language == "en-US"
    assert acceptance.platform == "MacIntel"
    assert acceptance.hardware_concurrency == "16"
    assert acceptance.device_memory_gb == "16 GB"
    assert acceptance.touch_support is True

    # Verify raw telemetry JSON contains captured headers and JS properties
    assert "headers" in acceptance.raw_telemetry
    assert acceptance.raw_telemetry["headers"].get("User-Agent") is not None
    assert acceptance.raw_telemetry["client_js"]["network"]["effectiveType"] == "4g"

    # Verify helper function and session cache
    assert has_user_accepted_latest_tos(normal_user, client.session) is True
    assert client.session.get("tos_accepted") == TermsOfServiceAcceptance.CURRENT_VERSION


@pytest.mark.django_db
def test_authenticated_user_after_acceptance_sees_executed_badge(client: Client, normal_user):
    """User who has accepted sees the active verification badge on /terms/."""
    TermsOfServiceAcceptance.objects.create(
        user=normal_user,
        version=TermsOfServiceAcceptance.CURRENT_VERSION,
        ip_address="203.0.113.19",
        screen_resolution="1920x1080",
    )
    client.force_login(normal_user)

    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()

    assert "Binding Agreement Active & Recorded" in content
    assert "203.0.113.19" in content
    assert "Continue to Kitchen" in content


# ---------------------------------------------------------------------------
# Mandatory Enforcement Middleware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_enforcement_middleware_redirects_unaccepted_user(client: Client, normal_user, settings):
    """
    When TOS enforcement is active, authenticated users who haven't accepted
    are intercepted and redirected to /terms/accept/?next=...
    """
    settings.ENFORCE_TOS_IN_TESTS = True
    client.force_login(normal_user)

    response = client.get("/mealplans/")
    assert response.status_code == 302
    assert reverse("core:terms_accept") in response.url
    assert "next=/mealplans/" in response.url


@pytest.mark.django_db
def test_enforcement_middleware_permits_accepted_user(client: Client, normal_user, settings):
    """Once user has accepted, requests pass through without interception."""
    settings.ENFORCE_TOS_IN_TESTS = True
    TermsOfServiceAcceptance.objects.create(
        user=normal_user,
        version=TermsOfServiceAcceptance.CURRENT_VERSION,
        ip_address="198.51.100.1",
    )
    client.force_login(normal_user)

    response = client.get(reverse("recipes:list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_enforcement_middleware_allows_core_terms_accept_without_redirect_loop(client: Client, normal_user, settings):
    """
    Unaccepted authenticated user requesting /core/terms/accept/ must get 200 OK
    and NOT be redirected back into itself in an infinite loop.
    """
    settings.ENFORCE_TOS_IN_TESTS = True
    client.force_login(normal_user)

    response = client.get(reverse("core:terms_accept"))
    assert response.status_code == 200
    assert "Shoppin Universal Terms of Service & Surrender of Rights" in response.content.decode()


@pytest.mark.django_db
def test_switch_persona_does_not_redirect_loop(client: Client, db, settings):
    """
    Switching personas via dev user picker does not cause redirect loops
    even when enforcement is active and previous referer was terms_accept.
    """
    settings.DEBUG = True
    settings.ENFORCE_TOS_IN_TESTS = True

    alice = User.objects.create_user(username="alice", password="password")

    # Referer is the terms accept page (common trigger for the infinite loop)
    response = client.get(
        reverse("core:switch_persona", args=["alice"]),
        HTTP_REFERER="http://testserver/core/terms/accept/?next=/",
    )
    # Must redirect to a clean app destination, NOT back to terms/accept
    assert response.status_code == 302
    assert response.url != "/core/terms/accept/"
    assert not response.url.startswith("/core/terms/accept")
    assert not response.url.startswith("/terms/accept")

    # Follow redirect to destination and verify 200 OK
    follow_resp = client.get(response.url)
    assert follow_resp.status_code == 200

    # User is authenticated as alice and has TOS accepted
    assert int(client.session["_auth_user_id"]) == alice.id
    assert has_user_accepted_latest_tos(alice, client.session)


@pytest.mark.django_db
def test_terms_accept_sanitizes_self_referential_next_url(client: Client, normal_user):
    """If next URL is self-referential to terms accept, sanitize to safe default."""
    client.force_login(normal_user)
    response = client.post(
        reverse("core:terms_accept"),
        {"affirmative_surrender": "true", "next": reverse("core:terms_accept")},
    )
    assert response.status_code == 302
    assert response.url == reverse("recipes:list")

