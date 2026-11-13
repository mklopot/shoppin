"""
End-to-end view tests for the main application entry points.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core.models import Workspace

User = get_user_model()


@pytest.mark.django_db
def test_homepage_unauthenticated_redirects_to_login(client):
    response = client.get(reverse('shopping:list'))
    assert response.status_code == 302
    assert reverse('core:login') in response.url


@pytest.mark.django_db
def test_homepage_renders_when_authenticated(client):
    user = User.objects.create(username="test_home_user")
    Workspace.objects.create(name="Home", owner=user)
    client.force_login(user)
    response = client.get(reverse('shopping:list'))
    assert response.status_code == 200
    assert b"Shoppin" in response.content
    assert b"Shopping List" in response.content
