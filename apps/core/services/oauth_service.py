"""
Google OAuth 2.0 / OpenID Connect authentication service.

Handles authorization URL generation, state validation, token exchange,
and user profile provisioning with zero third-party framework overhead.
"""

import logging
import os
import re
import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.urls import reverse

from apps.core.services.workspace_service import create_workspace

logger = logging.getLogger(__name__)
User = get_user_model()

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


def is_google_oauth_configured() -> bool:
    """Check if Google OAuth credentials have been configured."""
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    return bool(client_id.strip() and client_secret.strip())


def get_google_redirect_uri(request: HttpRequest) -> str:
    """
    Resolve the canonical Google OAuth callback URI.

    Uses GOOGLE_OAUTH_REDIRECT_URI if explicitly set in settings/env,
    otherwise dynamically constructs the absolute URI for core:google_callback.
    """
    configured = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "") or os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")
    if configured.strip():
        return configured.strip()
    return request.build_absolute_uri(reverse("core:google_callback"))


def get_google_auth_url(request: HttpRequest, next_url: str = "/") -> str:
    """
    Generate the Google OAuth 2.0 authorization URL.

    Stores cryptographic CSRF state token and post-login target in request.session.
    """
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or os.getenv("GOOGLE_CLIENT_ID", "")
    redirect_uri = get_google_redirect_uri(request)

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = next_url

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def _generate_unique_username(base_name: str) -> str:
    """Generate a clean, collision-free Django username."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", base_name).strip("_")
    if not clean:
        clean = "google_user"

    candidate = clean
    counter = 1
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{clean}_{counter}"
        counter += 1
    return candidate


def handle_google_callback(request: HttpRequest) -> tuple[Any | None, str, str | None]:
    """
    Process Google OAuth callback with authorization code.

    Exchanges authorization code for an access token, fetches profile,
    and returns (user_instance, next_redirect_url, error_message).
    """
    # 1. Verify CSRF State
    saved_state = request.session.get("oauth_state")
    returned_state = request.GET.get("state")
    next_url = request.session.get("oauth_next", "/")

    if not saved_state or not returned_state or saved_state != returned_state:
        logger.warning("Google OAuth state mismatch: saved='%s', returned='%s'", saved_state, returned_state)
        return None, next_url, "Invalid authentication state. Please try signing in again."

    # 2. Check for Google error response (e.g. user clicked cancel)
    if "error" in request.GET:
        err = request.GET.get("error", "access_denied")
        logger.info("Google OAuth returned error: %s", err)
        return None, next_url, f"Google authentication was cancelled or failed ({err})."

    code = request.GET.get("code")
    if not code:
        return None, next_url, "No authorization code received from Google."

    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = get_google_redirect_uri(request)

    # 3. Exchange authorization code for token
    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload, timeout=12)
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except Exception as exc:
        logger.error("Failed to exchange code for token with Google: %s", exc)
        return None, next_url, f"Failed to exchange authentication token with Google: {exc}"

    access_token = token_data.get("access_token")
    if not access_token:
        return None, next_url, "No access token in Google token response."

    # 4. Fetch User Information from Google
    try:
        userinfo_resp = requests.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=12,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except Exception as exc:
        logger.error("Failed to fetch userinfo from Google: %s", exc)
        return None, next_url, f"Could not retrieve user profile from Google: {exc}"

    email = userinfo.get("email", "").strip().lower()
    if not email:
        return None, next_url, "Google profile did not provide an email address."

    first_name = userinfo.get("given_name", "").strip()
    last_name = userinfo.get("family_name", "").strip()
    if not first_name and "name" in userinfo:
        parts = userinfo["name"].split(" ", 1)
        first_name = parts[0]
        if len(parts) > 1:
            last_name = parts[1]

    # 5. Lookup or Provision User
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        base_username = email.split("@")[0]
        unique_username = _generate_unique_username(base_username)
        user = User.objects.create_user(
            username=unique_username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()
        logger.info("Created new user via Google OAuth: %s (%s)", user.username, user.email)
    else:
        # Update name if previously blank
        updated = False
        if not user.first_name and first_name:
            user.first_name = first_name
            updated = True
        if not user.last_name and last_name:
            user.last_name = last_name
            updated = True
        if updated:
            user.save(update_fields=["first_name", "last_name"])

    # Ensure user has at least one workspace
    if not user.owned_workspaces.exists() and not user.workspace_memberships.exists():
        ws_name = f"{user.first_name or user.username}'s Kitchen"
        create_workspace(ws_name, user)

    # Store Google OAuth profile data in session for ToS acceptance audit record
    request.session["oauth_first_name"] = first_name
    request.session["oauth_last_name"] = last_name
    request.session["oauth_email"] = email

    # Clean up session state
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_next", None)
    request.session.pop("guest_mode", None)

    return user, next_url, None
