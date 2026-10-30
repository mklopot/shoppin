"""
Tests for Terms of Service: public viewing, mandatory acceptance gate,
standard legalese boilerplate, Google OAuth user data capture,
and enforcement middleware.
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
        first_name="Jane",
        last_name="Doe",
    )


# ---------------------------------------------------------------------------
# Public Viewing of Standard Bland Legalese Terms
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_can_view_terms_of_service(client: Client):
    """Guest can access /terms/ and see standard bland legalese boilerplate."""
    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()

    # Standard boilerplate headings and clauses
    assert "Terms of Service" in content
    assert "Acceptance of Terms" in content
    assert "User Content and Ownership" in content
    assert "Shoppin does not claim ownership of your User Content" in content
    assert "License to Shoppin" in content
    assert "Acceptable Use and Prohibited Activities" in content
    assert "Disclaimer of Warranties" in content
    assert "AS IS" in content
    assert "FITNESS FOR A PARTICULAR PURPOSE" in content
    assert "Limitation of Liability" in content
    assert "TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW" in content
    assert "Indemnification" in content
    assert "Governing Law and Jurisdiction" in content

    # Telemetry section and live sensors must be REMOVED
    assert "Comprehensive Real-Time Client Telemetry Ingestion" not in content
    assert "Friendly Device Insights" not in content
    assert "telemetry-local-time" not in content
    assert "telemetry-cores" not in content
    assert "telemetry-memory" not in content

    # Satirical / draconian levity must be REMOVED
    assert "Ancient Sumerian" not in content
    assert "Tierra del Fuego" not in content
    assert "ONE UNITED STATES CENT" not in content
    assert "Surrender of Rights" not in content
    assert "Delightful Subjugated Friend" not in content


# ---------------------------------------------------------------------------
# Mandatory Acceptance Gate Flow & UI
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_authenticated_user_at_terms_accept_does_not_show_tos_unless_clicked(client: Client, normal_user):
    """
    On the acceptance gate, the full ToS is NOT shown by default unless the link is clicked.
    The agreement checkbox is enabled and can be checked immediately without following the link.
    """
    client.force_login(normal_user)
    response = client.get(reverse("core:terms_accept"))
    assert response.status_code == 200
    content = response.content.decode()

    # The modal containing the terms is present but hidden initially
    assert 'id="terms-modal"' in content
    assert "hidden" in content

    # Link to view terms is present
    assert 'id="view-terms-link"' in content or 'href="#terms-modal"' in content

    # Agreement checkbox is present and NOT disabled
    assert 'name="agree_to_terms"' in content
    assert 'disabled' not in content.split('name="agree_to_terms"')[0].split('<input')[-1]

    # No scroll percent lock
    assert "0% read" not in content
    assert "tos-scroll-sentinel" not in content


@pytest.mark.django_db
def test_terms_acceptance_succeeds_without_verifying_link_followed(client: Client, normal_user):
    """
    User can check the box and submit without the site verifying if they followed the link.
    Acceptance is recorded immediately.
    """
    client.force_login(normal_user)
    response = client.post(
        reverse("core:terms_accept"),
        {"agree_to_terms": "1", "next": "/recipes/"},
    )
    assert response.status_code == 302
    assert response.url == "/recipes/"

    # Acceptance record created
    acceptance = TermsOfServiceAcceptance.objects.filter(user=normal_user).first()
    assert acceptance is not None
    assert acceptance.version == TermsOfServiceAcceptance.CURRENT_VERSION


@pytest.mark.django_db
def test_terms_acceptance_fails_without_checking_box(client: Client, normal_user):
    """POSTing without checking the agreement box is rejected."""
    client.force_login(normal_user)
    response = client.post(reverse("core:terms_accept"), {"next": "/recipes/"})
    assert response.status_code == 302
    assert reverse("core:terms_accept") in response.url
    assert not TermsOfServiceAcceptance.objects.filter(user=normal_user).exists()


@pytest.mark.django_db
def test_terms_acceptance_records_full_telemetry_and_google_names(client: Client, normal_user):
    """
    POSTing records client network, screen, and device signals, AND
    preserves first and last name from account / Google OAuth data.
    """
    client.force_login(normal_user)

    telemetry_payload = {
        "agree_to_terms": "1",
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
        "client_geolocation": "Timezone: America/New_York",
        "raw_client_telemetry": '{"screen":{"width":2560},"network":{"effectiveType":"4g"}}',
    }

    headers = {
        "HTTP_CF_CONNECTING_IP": "198.51.100.77",
        "HTTP_USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "HTTP_CF_IPCOUNTRY": "US",
        "HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9",
        "REMOTE_ADDR": "127.0.0.1",
    }

    response = client.post(reverse("core:terms_accept"), telemetry_payload, **headers)
    assert response.status_code == 302
    assert response.url == "/recipes/"

    acceptance = TermsOfServiceAcceptance.objects.filter(user=normal_user).first()
    assert acceptance is not None
    assert acceptance.version == TermsOfServiceAcceptance.CURRENT_VERSION
    # Google OAuth / User first and last name must be stored on record
    assert acceptance.first_name == "Jane"
    assert acceptance.last_name == "Doe"
    assert acceptance.raw_telemetry["first_name"] == "Jane"
    assert acceptance.raw_telemetry["last_name"] == "Doe"

    # Network & client device signals preserved
    assert acceptance.ip_address == "198.51.100.77"
    assert "Macintosh" in acceptance.user_agent
    assert acceptance.screen_resolution == "2560x1440"
    assert acceptance.viewport_size == "2560x1380"
    assert acceptance.timezone == "America/New_York"
    assert acceptance.client_language == "en-US"
    assert acceptance.platform == "MacIntel"
    assert acceptance.hardware_concurrency == "16"
    assert acceptance.device_memory_gb == "16 GB"
    assert acceptance.touch_support is True

    # Raw telemetry contains headers dump and client JS details
    assert "headers" in acceptance.raw_telemetry
    assert acceptance.raw_telemetry["headers"].get("User-Agent") is not None

    # Verify session cache
    assert has_user_accepted_latest_tos(normal_user, client.session) is True
    assert client.session.get("tos_accepted") == TermsOfServiceAcceptance.CURRENT_VERSION


@pytest.mark.django_db
def test_terms_acceptance_captures_google_oauth_session_names(client: Client):
    """
    If a user signs in via Google OAuth, first and last name stored in session
    are captured as part of the ToS acceptance record.
    """
    oauth_user = User.objects.create_user(
        username="google_user_1",
        email="googleuser@example.com",
    )
    client.force_login(oauth_user)

    # Simulate Google OAuth session data
    session = client.session
    session["oauth_first_name"] = "Michael"
    session["oauth_last_name"] = "Scott"
    session.save()

    response = client.post(
        reverse("core:terms_accept"),
        {"agree_to_terms": "1", "next": "/recipes/"},
    )
    assert response.status_code == 302

    acceptance = TermsOfServiceAcceptance.objects.filter(user=oauth_user).first()
    assert acceptance is not None
    assert acceptance.first_name == "Michael"
    assert acceptance.last_name == "Scott"
    assert acceptance.raw_telemetry["first_name"] == "Michael"
    assert acceptance.raw_telemetry["last_name"] == "Scott"


@pytest.mark.django_db
def test_authenticated_user_after_acceptance_sees_executed_badge(client: Client, normal_user):
    """User who has accepted sees the quiet acceptance status on /terms/."""
    TermsOfServiceAcceptance.objects.create(
        user=normal_user,
        version=TermsOfServiceAcceptance.CURRENT_VERSION,
        first_name="Jane",
        last_name="Doe",
        ip_address="203.0.113.19",
    )
    client.force_login(normal_user)

    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()

    assert "Terms Accepted" in content
    assert "Return to App" in content


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
    assert "Terms of Service" in response.content.decode()


@pytest.mark.django_db
def test_switch_persona_does_not_redirect_loop(client: Client, db, settings):
    """
    Switching personas via dev user picker does not cause redirect loops
    even when enforcement is active and previous referer was terms_accept.
    """
    settings.DEBUG = True
    settings.ENFORCE_TOS_IN_TESTS = True

    alice = User.objects.create_user(username="alice", password="password")

    response = client.get(
        reverse("core:switch_persona", args=["alice"]),
        HTTP_REFERER="http://testserver/core/terms/accept/?next=/",
    )
    assert response.status_code == 302
    assert response.url != "/core/terms/accept/"
    assert not response.url.startswith("/core/terms/accept")
    assert not response.url.startswith("/terms/accept")

    follow_resp = client.get(response.url)
    assert follow_resp.status_code == 200

    assert int(client.session["_auth_user_id"]) == alice.id
    assert has_user_accepted_latest_tos(alice, client.session)


@pytest.mark.django_db
def test_terms_accept_sanitizes_self_referential_next_url(client: Client, normal_user):
    """If next URL is self-referential to terms accept, sanitize to safe default."""
    client.force_login(normal_user)
    response = client.post(
        reverse("core:terms_accept"),
        {"agree_to_terms": "1", "next": reverse("core:terms_accept")},
    )
    assert response.status_code == 302
    assert response.url == reverse("recipes:list")
