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
        if settings.DEBUG and not is_testing:
            if hasattr(request, "user") and not request.user.is_authenticated:
                admin_user = (
                    User.objects.filter(username="admin").first()
                    or User.objects.filter(is_superuser=True).first()
                    or User.objects.first()
                )
                if admin_user:
                    login(request, admin_user)

        return self.get_response(request)
