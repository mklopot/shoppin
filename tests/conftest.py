import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Workspace

User = get_user_model()


@pytest.fixture(autouse=True)
def media_root_tmp(settings, tmp_path):
    """Ensure tests run against an isolated temporary MEDIA_ROOT."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        username="test_auth_user",
        email="auth_user@example.com",
        password="testpassword123",
    )
    workspace = Workspace.objects.create(name="Test Workspace", owner=user)
    return user, workspace
