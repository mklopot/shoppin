"""
Terms of Service views: public viewing, client telemetry capture,
and mandatory acceptance enforcement.
"""

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.models import TermsOfServiceAcceptance
from apps.core.services.tos_service import (
    get_client_ip,
    get_geolocation_hint,
    has_user_accepted_latest_tos,
    record_tos_acceptance,
)


def terms_view(request: HttpRequest) -> HttpResponse:
    """
    Render public Terms of Service page.
    """
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    has_accepted = False
    acceptance_record = None

    if is_authenticated:
        has_accepted = has_user_accepted_latest_tos(user, getattr(request, "session", None))
        if has_accepted:
            acceptance_record = TermsOfServiceAcceptance.objects.filter(
                user=user,
                version=TermsOfServiceAcceptance.CURRENT_VERSION,
            ).first()

    next_url = request.GET.get("next") or reverse("recipes:list")

    context: dict[str, Any] = {
        "version": TermsOfServiceAcceptance.CURRENT_VERSION,
        "is_authenticated": is_authenticated,
        "has_accepted": has_accepted,
        "acceptance_record": acceptance_record,
        "next": next_url,
        "client_ip": get_client_ip(request),
        "geo_hint": get_geolocation_hint(request),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }
    return render(request, "core/terms_of_service.html", context)


@login_required
def terms_accept_view(request: HttpRequest) -> HttpResponse:
    """
    Handle mandatory terms acceptance for authenticated users.
    Collects client-side and server-side telemetry.
    """
    user = request.user
    next_url = request.GET.get("next") or request.POST.get("next") or reverse("recipes:list")

    disallowed_prefixes = (
        "/terms",
        "/core/terms",
        "/login",
        "/accounts/login",
        "/core/login",
        "/logout",
        "/accounts/logout",
        "/core/logout",
        "/core/dev",
    )
    if not next_url.startswith("/") or any(next_url.startswith(p) for p in disallowed_prefixes):
        next_url = reverse("recipes:list")

    if has_user_accepted_latest_tos(user, request.session):
        return redirect(next_url)

    if request.method == "POST":
        agreed = request.POST.get("affirmative_surrender") in ("true", "1", "on", True)
        if not agreed:
            messages.error(
                request,
                "You must unconditionally check the box confirming your total surrender of rights to proceed.",
            )
            return redirect(f"{reverse('core:terms_accept')}?next={next_url}")

        record = record_tos_acceptance(user, request)
        messages.success(
            request,
            f"Terms of Service executed successfully. Recorded under Audit ID #{record.id} from IP {record.ip_address}.",
        )
        return redirect(next_url)

    context: dict[str, Any] = {
        "version": TermsOfServiceAcceptance.CURRENT_VERSION,
        "is_authenticated": True,
        "has_accepted": False,
        "next": next_url,
        "client_ip": get_client_ip(request),
        "geo_hint": get_geolocation_hint(request),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        "is_mandatory_gate": True,
    }
    return render(request, "core/terms_of_service.html", context)
