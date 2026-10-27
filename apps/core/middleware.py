"""
Development authentication and session middleware.

Automatically logs in a default development user ('admin') when running
in DEBUG mode and no user is currently authenticated in the session.
"""

import sys
from typing import Callable

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpRequest, HttpResponse

User = get_user_model()


class DevAutoLoginMiddleware:
    """
    Middleware that automatically logs in the default development user ('admin')
    when running locally in DEBUG mode and no user is currently authenticated.

    This ensures smooth developer testing across browser tabs without requiring
    manual login forms or credentials, and avoids unexpected 403 Forbidden errors.
    Bypassed completely during automated test runs (pytest).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize middleware with next handler."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process request and auto-login development user if unauthenticated in DEBUG mode.

        Args:
            request: HttpRequest instance.

        Returns:
            HttpResponse from downstream middleware/view.
        """
        is_testing = "pytest" in sys.modules or (len(sys.argv) > 1 and sys.argv[1] == "test")
        dev_auto_login = getattr(settings, "DEV_AUTO_LOGIN", False)
        guest_mode = bool(request.session.get("guest_mode", False)) if hasattr(request, "session") else False

        if settings.DEBUG and not is_testing and dev_auto_login and not guest_mode:
            if hasattr(request, "user") and not request.user.is_authenticated:
                admin_user = (
                    User.objects.filter(username="admin").first()
                    or User.objects.filter(is_superuser=True).first()
                    or User.objects.first()
                )
                if admin_user:
                    login(request, admin_user)

        return self.get_response(request)


class TermsOfServiceEnforcementMiddleware:
    """
    Middleware that enforces mandatory acceptance of the Terms of Service.

    Any authenticated user who has not executed the latest Terms of Service
    is intercepted and redirected to the terms acceptance gate.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Initialize middleware with next handler."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Intercept authenticated requests lacking current TOS acceptance.
        """
        user = getattr(request, "user", None)
        is_testing = "pytest" in sys.modules or (len(sys.argv) > 1 and sys.argv[1] == "test")
        enforce_in_tests = getattr(settings, "ENFORCE_TOS_IN_TESTS", False)

        if is_testing and not enforce_in_tests:
            return self.get_response(request)

        if user and user.is_authenticated:
            exempt_prefixes = (
                "/terms/",
                "/core/terms/",
                "/accounts/logout/",
                "/logout/",
                "/core/logout/",
                "/accounts/login/",
                "/login/",
                "/core/login/",
                "/core/dev/",
                "/static/",
                "/media/",
                "/admin/",
            )
            path = request.path_info
            if not any(path.startswith(prefix) for prefix in exempt_prefixes):
                from urllib.parse import quote

                from django.shortcuts import redirect
                from django.urls import reverse

                from apps.core.services.tos_service import has_user_accepted_latest_tos

                if not has_user_accepted_latest_tos(user, getattr(request, "session", None)):
                    terms_accept_url = reverse("core:terms_accept")
                    if not path.startswith(terms_accept_url) and not path.startswith("/terms/accept"):
                        return redirect(f"{terms_accept_url}?next={quote(request.get_full_path())}")

        return self.get_response(request)
