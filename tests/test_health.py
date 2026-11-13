"""
Basic sanity tests for Django configuration and installed apps.
"""

from django.conf import settings


def test_django_configured():
    assert settings.INSTALLED_APPS is not None
    assert 'apps.shopping.apps.ShoppingConfig' in settings.INSTALLED_APPS
