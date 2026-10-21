import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_homepage_renders(client):
    response = client.get(reverse('shopping:list'))
    assert response.status_code == 200
    assert b"Shoppin" in response.content
    assert b"Shopping List" in response.content
