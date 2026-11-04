"""
Tests for DMCA Notice, safe harbor compliance, repeat infringer strike tracking,
and footer/terms integration.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.core.models import UserDMCAProfile

User = get_user_model()


@pytest.fixture
def normal_user(db):
    return User.objects.create_user(
        username="culinary_author",
        email="author@example.com",
        password="test_password_123",
        first_name="Alice",
        last_name="Waters",
    )


@pytest.fixture
def banned_infringer_user(db):
    user = User.objects.create_user(
        username="serial_pirate",
        email="pirate@example.com",
        password="test_password_123",
    )
    profile, _ = UserDMCAProfile.objects.get_or_create(user=user)
    profile.strikes = 3
    profile.is_banned = True
    profile.save()
    return user


# ---------------------------------------------------------------------------
# Public DMCA Notice & Safe Harbor Statutory Elements
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_guest_can_view_dmca_page(client: Client):
    """Anonymous visitors can access /dmca/ and view full statutory disclosures."""
    response = client.get(reverse("core:dmca"))
    assert response.status_code == 200
    content = response.content.decode()

    # Core titles and agent identification
    assert "DMCA Notice &amp; Copyright Policy" in content or "DMCA Notice & Copyright Policy" in content
    assert "DMCA Designated Agent" in content
    assert "dmca@recipe.klopot.tech" in content
    assert "Denver, Colorado" in content

    # 17 U.S.C. 512(c)(3) takedown requirements
    assert "Physical or Electronic Signature" in content
    assert "Identification of the Copyrighted Work" in content
    assert "Identification of the Infringing Material" in content
    assert "Good Faith Statement" in content
    assert "Statement Under Penalty of Perjury" in content

    # 17 U.S.C. 512(f) misrepresentation warning
    assert "512(f)" in content
    assert "knowingly materially misrepresents" in content

    # 17 U.S.C. 512(g)(3) counter-notification
    assert "Counter-Notification Procedure" in content
    assert "10, nor more than 14, business days" in content

    # 17 U.S.C. 512(i) repeat infringer policy
    assert "Repeat Infringer Policy" in content
    assert "three (3) copyright strikes" in content


@pytest.mark.django_db
def test_authenticated_user_can_view_dmca_page(client: Client, normal_user):
    """Authenticated users can access /dmca/."""
    client.force_login(normal_user)
    response = client.get(reverse("core:dmca"))
    assert response.status_code == 200
    assert "DMCA Designated Agent" in response.content.decode()


# ---------------------------------------------------------------------------
# UI Navigation & Terms of Service Integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_footer_contains_dmca_link(client: Client):
    """Site-wide footer in base template renders a link to /dmca/."""
    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()
    dmca_url = reverse("core:dmca")
    assert f'href="{dmca_url}"' in content
    assert ">DMCA<" in content


@pytest.mark.django_db
def test_terms_of_service_references_dmca_policy(client: Client):
    """Terms of Service includes a dedicated DMCA section with cross-link."""
    response = client.get(reverse("core:terms"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "DMCA Copyright Infringement and Repeat Infringer Policy" in content
    assert "dmca@recipe.klopot.tech" in content
    assert reverse("core:dmca") in content


# ---------------------------------------------------------------------------
# User Model DMCA Strike Tracking & Auto-Ban
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_dmca_strikes_property_and_initialization(normal_user):
    """A user automatically has 0 strikes on creation."""
    assert normal_user.dmca_strikes == 0
    profile = normal_user.dmca_profile
    assert profile.strikes == 0
    assert not profile.is_banned
    assert profile.strike_history == []


@pytest.mark.django_db
def test_record_strike_escalation_and_auto_ban(normal_user):
    """Recording strikes logs audit entries and triggers auto-ban on 3rd strike."""
    profile = normal_user.dmca_profile

    # First strike
    strikes = profile.record_strike(
        notice_id="CASE-001",
        affected_urls=["https://recipe.klopot.tech/recipes/1/"],
        notes="First offense: verbatim copyright infringement",
    )
    assert strikes == 1
    assert profile.strikes == 1
    assert not profile.is_banned
    assert len(profile.strike_history) == 1
    assert profile.strike_history[0]["notice_id"] == "CASE-001"

    # Second strike
    strikes = profile.record_strike(notice_id="CASE-002")
    assert strikes == 2
    assert not profile.is_banned

    # Third strike: triggers automatic ban
    strikes = profile.record_strike(notice_id="CASE-003")
    assert strikes == 3
    assert profile.is_banned is True

    # User property reflects updated strikes
    normal_user.refresh_from_db()
    assert normal_user.dmca_strikes == 3


@pytest.mark.django_db
def test_remove_strike_clears_ban(normal_user):
    """Removing a strike (e.g. uncontested counter-notice) decrements count and un-bans."""
    profile = normal_user.dmca_profile
    profile.record_strike("CASE-001")
    profile.record_strike("CASE-002")
    profile.record_strike("CASE-003")
    assert profile.is_banned is True

    # Remove strike
    remaining = profile.remove_strike(reason="Uncontested counter-notification")
    assert remaining == 2
    assert profile.strikes == 2
    assert profile.is_banned is False
    assert len(profile.strike_history) == 4  # 3 added + 1 removed log


# ---------------------------------------------------------------------------
# Repeat Infringer Access Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_banned_repeat_infringer_cannot_create_recipe(client: Client, banned_infringer_user):
    """Repeat infringer with 3 strikes cannot access recipe creation view."""
    client.force_login(banned_infringer_user)
    response = client.get(reverse("recipes:create"), follow=True)
    assert response.status_code == 200
    # User should be redirected to recipe list with error message
    content = response.content.decode()
    assert "restricted from creating or importing recipes due to repeated copyright infringement" in content
