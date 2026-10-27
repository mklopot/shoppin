"""
Authentication views: login, logout, and Google OAuth 2.0 flow.
"""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.services.oauth_service import (
    get_google_auth_url,
    handle_google_callback,
    is_google_oauth_configured,
)
from apps.core.services.tos_service import has_user_accepted_latest_tos


def login_view(request: HttpRequest) -> HttpResponse:
    """
    Render login page with Google OAuth button, standard auth, and dev personas.
    """
    if request.user.is_authenticated:
        next_url = request.GET.get("next") or reverse("recipes:list")
        return redirect(next_url)

    next_url = request.GET.get("next", "")
    form = AuthenticationForm(request)

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            request.session.pop("guest_mode", None)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            target = next_url if next_url and next_url.startswith("/") else reverse("recipes:list")
            if not has_user_accepted_latest_tos(user, request.session):
                return redirect(f"{reverse('core:terms_accept')}?next={target}")
            return redirect(target)
        else:
            messages.error(request, "Invalid username or password.")

    context: dict[str, Any] = {
        "form": form,
        "next": next_url,
        "is_google_configured": is_google_oauth_configured(),
        "google_login_url": reverse("core:google_login") + (f"?next={next_url}" if next_url else ""),
        "debug_mode": settings.DEBUG,
    }
    return render(request, "core/login.html", context)


def google_login_view(request: HttpRequest) -> HttpResponse:
    """
    Initiate Google OAuth 2.0 flow or show setup guide if unconfigured.
    """
    next_url = request.GET.get("next") or reverse("recipes:list")

    if not is_google_oauth_configured():
        if settings.DEBUG:
            messages.warning(
                request,
                "Google OAuth credentials are not configured yet in .env (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).",
            )
            return render(
                request,
                "core/google_setup_guide.html",
                {
                    "next": next_url,
                    "redirect_uri": request.build_absolute_uri(reverse("core:google_callback")),
                },
            )
        else:
            messages.error(request, "Google authentication is not configured on this server.")
            return redirect(reverse("core:login"))

    auth_url = get_google_auth_url(request, next_url=next_url)
    return redirect(auth_url)


def google_callback_view(request: HttpRequest) -> HttpResponse:
    """
    Process authorization callback from Google.
    """
    user, next_url, error = handle_google_callback(request)

    if error or not user:
        messages.error(request, error or "Could not authenticate with Google.")
        return redirect(reverse("core:login") + (f"?next={next_url}" if next_url else ""))

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(settings.SESSION_COOKIE_AGE)
    messages.success(request, f"Signed in as {user.email or user.username}.")
    target = next_url if next_url and next_url.startswith("/") else reverse("recipes:list")
    if not has_user_accepted_latest_tos(user, request.session):
        return redirect(f"{reverse('core:terms_accept')}?next={target}")
    return redirect(target)


def logout_view(request: HttpRequest) -> HttpResponse:
    """
    Log out the currently active user and switch to guest mode.
    """
    logout(request)
    request.session["guest_mode"] = True
    messages.info(request, "You have been logged out. You are now browsing as a guest.")
    next_url = request.GET.get("next") or reverse("recipes:list")
    if not next_url.startswith("/"):
        next_url = reverse("recipes:list")
    return redirect(next_url)
