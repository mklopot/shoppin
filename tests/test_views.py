import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_homepage_renders(client):
    response = client.get(reverse('index'))
    assert response.status_code == 200
    assert b"Shoppin" in response.content
    assert b"Tailwind CSS" in response.content or b"tailwind.config" in response.content
