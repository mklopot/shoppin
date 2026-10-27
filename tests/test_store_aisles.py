"""
Unit and service tests for store aisle resolution, Kroger API integration, and natural walking order.
"""

from decimal import Decimal

import pytest

from apps.shopping.models import (
    ItemStatus,
    ShoppingList,
    ShoppingListItem,
    StoreItemAisle,
    StoreLocation,
)
from apps.shopping.services.store_service import (
    get_nearest_stores,
    haversine_distance,
    resolve_store_aisle,
)


@pytest.mark.django_db
def test_haversine_distance():
    # Denver to Boulder is approx 24-25 miles
    denver_lat, denver_lon = 39.7392, -104.9903
    boulder_lat, boulder_lon = 40.0150, -105.2705
    dist = haversine_distance(denver_lat, denver_lon, boulder_lat, boulder_lon)
    assert 22 <= dist <= 27


@pytest.mark.django_db
def test_nearest_stores():
    StoreLocation.objects.all().delete()
    king = StoreLocation.objects.create(
        name="King Soopers Downtown",
        chain="kroger",
        latitude=39.75,
        longitude=-104.99,
    )
    StoreLocation.objects.create(
        name="Safeway South",
        chain="safeway",
        latitude=39.65,
        longitude=-104.99,
    )

    # Position close to downtown Denver
    nearest = get_nearest_stores(39.74, -104.99, limit=2)
    assert len(nearest) == 2
    assert nearest[0]["store"] == king
    assert nearest[0]["distance_miles"] < nearest[1]["distance_miles"]


@pytest.mark.django_db
def test_get_nearest_five_stores(client):
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    from apps.core.models import Workspace
    User = get_user_model()
    admin = User.objects.create_user(username="store_test_user")
    ws = Workspace.objects.create(name="Store Test WS", owner=admin)
    s_list = ShoppingList.objects.create(name="Store Test List", workspace=ws, owner=admin)
    client.force_login(admin)

    # Query from LoDo coordinates (39.753, -105.000)
    nearest = get_nearest_stores(39.753, -105.000, limit=5)
    assert len(nearest) == 5

    # Distances must be strictly non-decreasing
    for i in range(len(nearest) - 1):
        assert nearest[i]["distance_miles"] <= nearest[i + 1]["distance_miles"]

    store_names = [n["store"].name for n in nearest]
    # Whole Foods Union Station and King Soopers Chestnut are much closer than Cherry Creek
    assert "Whole Foods Market (Union Station)" in store_names
    assert "King Soopers #01400115 (Chestnut / LoDo)" in store_names

    # Test POST to find_nearest_store endpoint returns modal with 5 stores
    response = client.post(
        reverse("shopping:nearest_store"),
        {
            "latitude": "39.753",
            "longitude": "-105.000",
        },
    )
    assert response.status_code == 200
    assert b"Stores Closest to You" in response.content
    assert b"Whole Foods Market (Union Station)" in response.content
    assert b"Select Store" in response.content

    # Select the first store
    first_store = nearest[0]["store"]
    set_resp = client.post(
        reverse("shopping:set_store"),
        {"store_id": str(first_store.id)},
    )
    assert set_resp.status_code == 200
    s_list.refresh_from_db()
    assert s_list.active_store == first_store


@pytest.mark.django_db
def test_store_aisle_resolution_and_learning():
    safeway = StoreLocation.objects.create(
        name="Local Safeway",
        chain="safeway",
        latitude=39.70,
        longitude=-104.98,
    )

    # 1. Unmapped item falls back to category department
    res = resolve_store_aisle(safeway, "avocados")
    assert res["aisle_name"].lower() == "produce"
    assert res["source"] == "default"

    # 2. User manually learns an aisle for this store
    StoreItemAisle.objects.filter(store=safeway, item_name_normalized="avocado").update(
        aisle_name="Aisle 1 - Front Endcap",
        source="manual",
    )

    # Re-resolving should now hit the learned aisle
    res2 = resolve_store_aisle(safeway, "avocado")
    assert res2["aisle_name"] == "Aisle 1 - Front Endcap"
    assert res2["source"] == "manual"


@pytest.mark.django_db
def test_shopping_list_effective_aisle():
    store = StoreLocation.objects.create(name="Neighborhood Market", chain="other")
    s_list = ShoppingList.objects.create(name="Weekly List", active_store=store)

    item = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Apples",
        amount=Decimal("3.00"),
        category="produce",
        status=ItemStatus.NEED,
    )

    # Without store mapping, returns category
    assert item.get_effective_aisle() == "Produce"

    # With store mapping
    StoreItemAisle.objects.create(
        store=store,
        item_name_normalized="apple",
        aisle_name="Aisle 2 Produce",
        source="manual",
    )

    assert item.get_effective_aisle() == "Aisle 2 Produce"


def test_aisle_natural_sorting():
    from apps.shopping.services.store_service import get_aisle_sort_key

    unordered_aisles = [
        "Aisle 35",
        "Aisle 36",
        "Aisle 14",
        "Produce Stand",
        "Bakery",
        "Aisle 1",
        "Meat Counter",
        "Dairy",
    ]
    sorted_aisles = sorted(unordered_aisles, key=get_aisle_sort_key)
    assert sorted_aisles == [
        "Produce Stand",
        "Bakery",
        "Meat Counter",
        "Aisle 1",
        "Aisle 14",
        "Aisle 35",
        "Aisle 36",
        "Dairy",
    ]

@pytest.mark.django_db
def test_nearest_stores_deduplication():
    # Create duplicate records at the same address/chain
    StoreLocation.objects.create(
        name="Safeway Corona Duplicate",
        chain="safeway",
        external_store_id="1466",
        address="560 Corona St",
        latitude=39.7259,
        longitude=-104.9733,
    )
    # Query at Corona St coords
    nearest = get_nearest_stores(39.726, -104.973, limit=5)
    addresses = [n["store"].address for n in nearest if n["store"].address]
    assert len(addresses) == len(set(addresses)), f"Duplicate addresses found in nearest: {addresses}"
