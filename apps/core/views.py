"""
Core views for landing or health dashboard endpoints.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def index(request: HttpRequest) -> HttpResponse:
    """Render the main application landing page."""
    return render(request, "core/index.html")
