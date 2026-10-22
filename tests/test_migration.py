"""
Integration tests for the legacy YAML data migration command.
"""

import pytest
from django.core.management import call_command

from apps.recipes.models import Ingredient, Recipe
from apps.shopping.models import ShoppingList


@pytest.mark.django_db
def test_import_legacy_data_command():
    call_command("import_legacy_data", overwrite=True)

    assert Recipe.objects.count() >= 80
    assert Ingredient.objects.count() >= 500
    assert ShoppingList.objects.filter(is_preset=True).count() == 12

    # Verify a specific recipe
    tacos = Recipe.objects.get(name="tacos and burritos")
    assert tacos.ingredients.count() > 0

    avocado = tacos.ingredients.filter(name__icontains="avocado").first()
    assert avocado is not None
    assert avocado.amount >= 1

    # Verify preset list
    ezra = ShoppingList.objects.get(name="Ezra's Lunches")
    assert ezra.is_preset is True
    assert ezra.items.count() > 0
