import pytest


@pytest.fixture(autouse=True)
def media_root_tmp(settings, tmp_path):
    """Ensure tests run against an isolated temporary MEDIA_ROOT."""
    settings.MEDIA_ROOT = tmp_path / "media"
