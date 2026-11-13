"""
Terms of Service Service: telemetry extraction, agreement verification,
and audit trail recording.
"""

import json
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.http import HttpRequest

from apps.core.models import TermsOfServiceAcceptance


def get_client_ip(request: HttpRequest) -> str:
    """
    Extract the most accurate client IP address from proxy headers or remote address.
    """
    for header in (
        "HTTP_CF_CONNECTING_IP",
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
        "REMOTE_ADDR",
    ):
        val = request.META.get(header)
        if val:
            # If comma-separated, take the first untrusted client IP
            return val.split(",")[0].strip()
    return "127.0.0.1"


def get_geolocation_hint(request: HttpRequest) -> str:
    """
    Extract geolocation hints from CDN / edge proxy headers if present.
    """
    country = (
        request.META.get("HTTP_CF_IPCOUNTRY")
        or request.META.get("HTTP_X_GEO_COUNTRY")
        or request.META.get("HTTP_GEOIP_COUNTRY_NAME")
        or request.META.get("HTTP_X_COUNTRY_CODE")
        or ""
    )
    city = request.META.get("HTTP_X_GEO_CITY") or request.META.get("HTTP_CF_IPCITY") or ""
    region = request.META.get("HTTP_X_GEO_REGION") or ""

    parts = [p for p in (city, region, country) if p]
    if parts:
        return ", ".join(parts)

    # Check client reported timezone as fallback geo indication
    tz = request.POST.get("timezone", "").strip()
    if tz:
        return f"Timezone: {tz}"
    return "Unknown / Undisclosed Geolocation"


def has_user_accepted_latest_tos(
    user: AbstractBaseUser | AnonymousUser | None,
    session: Any = None,
) -> bool:
    """
    Check if an authenticated user has executed the current Terms of Service.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    # Check session cache first for fast path
    if session and session.get("tos_accepted") == TermsOfServiceAcceptance.CURRENT_VERSION:
        return True

    accepted = TermsOfServiceAcceptance.objects.filter(
        user=user,
        version=TermsOfServiceAcceptance.CURRENT_VERSION,
    ).exists()

    if accepted and session:
        session["tos_accepted"] = TermsOfServiceAcceptance.CURRENT_VERSION

    return accepted


def record_tos_acceptance(
    user: AbstractBaseUser | AnonymousUser | None,
    request: HttpRequest,
) -> TermsOfServiceAcceptance:
    """
    Record legally binding acceptance of the Terms of Service
    along with user identity (including first and last name from account / OAuth)
    and client network and device details.
    """
    post = request.POST
    ip_address = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    geolocation = post.get("client_geolocation", "").strip() or get_geolocation_hint(request)

    actual_user = user if (user and getattr(user, "is_authenticated", False)) else None

    # Resolve first and last name from authenticated user (e.g. populated via Google OAuth) or session/request
    first_name = ""
    last_name = ""
    if actual_user:
        first_name = (getattr(actual_user, "first_name", "") or "").strip()
        last_name = (getattr(actual_user, "last_name", "") or "").strip()

    if hasattr(request, "session"):
        if not first_name:
            first_name = (request.session.get("oauth_first_name", "") or "").strip()
        if not last_name:
            last_name = (request.session.get("oauth_last_name", "") or "").strip()

    if not first_name:
        first_name = post.get("first_name", "").strip()
    if not last_name:
        last_name = post.get("last_name", "").strip()

    screen_res = post.get("screen_resolution", "").strip()
    viewport = post.get("viewport_size", "").strip()
    color_depth = post.get("color_depth", "").strip()
    pixel_ratio = post.get("pixel_ratio", "").strip()
    timezone = post.get("timezone", "").strip()
    language = post.get("client_language", "").strip() or request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    platform = post.get("platform", "").strip()
    hardware_concurrency = post.get("hardware_concurrency", "").strip()
    device_memory = post.get("device_memory_gb", "").strip()
    touch_support = post.get("touch_support") in ("true", "1", True)

    # Parse any raw JSON telemetry submitted by client script
    client_extra = {}
    raw_client_json = post.get("raw_client_telemetry", "").strip()
    if raw_client_json:
        try:
            client_extra = json.loads(raw_client_json)
        except Exception:
            client_extra = {"raw_unparsed": raw_client_json}

    # Harvest all HTTP headers from request
    headers_dump = {
        k[5:].replace("_", "-").title(): v
        for k, v in request.META.items()
        if k.startswith("HTTP_")
    }

    full_telemetry = {
        "user_id": actual_user.id if actual_user else None,
        "username": getattr(actual_user, "username", ""),
        "email": getattr(actual_user, "email", ""),
        "first_name": first_name,
        "last_name": last_name,
        "headers": headers_dump,
        "client_js": client_extra,
        "remote_addr": request.META.get("REMOTE_ADDR"),
        "method": request.method,
        "path": request.path,
        "is_secure": request.is_secure(),
    }

    record = TermsOfServiceAcceptance.objects.create(
        user=actual_user,
        version=TermsOfServiceAcceptance.CURRENT_VERSION,
        first_name=first_name,
        last_name=last_name,
        ip_address=ip_address,
        user_agent=user_agent,
        geolocation=geolocation,
        screen_resolution=screen_res,
        viewport_size=viewport,
        color_depth=color_depth,
        pixel_ratio=pixel_ratio,
        timezone=timezone,
        client_language=language,
        platform=platform,
        hardware_concurrency=hardware_concurrency,
        device_memory_gb=device_memory,
        touch_support=touch_support,
        raw_telemetry=full_telemetry,
    )

    if hasattr(request, "session"):
        request.session["tos_accepted"] = TermsOfServiceAcceptance.CURRENT_VERSION

    return record
