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
    assert any("Chestnut / LoDo" in name for name in store_names)

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

    # 1. Unmapped item without chain API returns None (leaves aisle blank)
    res = resolve_store_aisle(safeway, "avocados")
    assert res is None

    # 2. User manually learns an aisle for this store
    StoreItemAisle.objects.create(
        store=safeway,
        item_name_normalized="avocado",
        aisle_name="Aisle 1 - Front Endcap",
        source="manual",
    )

    # Re-resolving should now hit the learned aisle
    res2 = resolve_store_aisle(safeway, "avocado")
    assert res2 is not None
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

    # Without store mapping or API, returns empty string (never category)
    assert item.get_effective_aisle() == ""

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

@pytest.mark.django_db
def test_select_store_updates_dropdown_and_aisles(client):
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    from apps.core.models import Workspace

    User = get_user_model()
    user = User.objects.create_user(username="leetsdale_tester")
    ws = Workspace.objects.create(name="Leetsdale WS", owner=user)
    s_list = ShoppingList.objects.create(name="Leetsdale List", workspace=ws, owner=user)
    client.force_login(user)

    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Cheddar Cheese",
        amount=Decimal("1.00"),
        category="dairy",
        status=ItemStatus.NEED,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="French Baguette",
        amount=Decimal("1.00"),
        category="bakery",
        status=ItemStatus.NEED,
    )

    leetsdale = StoreLocation.objects.filter(name__icontains="Leetsdale").first()
    assert leetsdale is not None

    response = client.post(
        reverse("shopping:set_store") + "?group_by=aisle",
        {"store_id": str(leetsdale.id)},
    )
    assert response.status_code == 200
    s_list.refresh_from_db()
    assert s_list.active_store == leetsdale

    content = response.content.decode("utf-8")
    assert f'value="{leetsdale.id}" selected' in content
    assert 'aria-pressed="true"' in content
    assert 'Active store set to' in content
    assert 'Leetsdale' in content
    # When Kroger API is configured, items group under their genuine store departments (e.g. Dairy)
    assert "Dairy" in content or "Other" in content


@pytest.mark.django_db
def test_kroger_api_aisle_resolution_and_list_population(client, monkeypatch):
    """
    Test that when Kroger API is configured, setting a Kroger store or viewing list
    auto-resolves actual store aisles for existing list items, while unmapped items
    remain blank (never displaying category names).
    """
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.urls import reverse

    from apps.core.models import Workspace
    from apps.shopping.services.store_service import kroger_client

    User = get_user_model()
    user = User.objects.create_user(username="api_aisle_user")
    ws = Workspace.objects.create(name="API Aisle WS", owner=user)
    s_list = ShoppingList.objects.create(name="API Aisle List", workspace=ws, owner=user)
    client.force_login(user)

    item1 = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Cheddar Cheese",
        amount=Decimal("1.00"),
        category="dairy",
        status=ItemStatus.NEED,
    )
    item2 = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="French Baguette",
        amount=Decimal("1.00"),
        category="bakery",
        status=ItemStatus.NEED,
    )

    kroger_store = StoreLocation.objects.create(
        name="King Soopers Test Store",
        chain="kroger",
        external_store_id="01400018",
        latitude=39.71,
        longitude=-104.91,
    )

    def mock_lookup(location_id, term):
        if "cheddar" in term.lower():
            return {
                "aisle_name": "Aisle 36",
                "bay_number": "2",
                "sequence_order": 136,
            }
        return None

    with patch.object(type(kroger_client), "is_configured", True), \
         patch.object(kroger_client, "lookup_product_aisle", side_effect=mock_lookup):

        # 1. Select the store (POST /set-store)
        resp = client.post(
            reverse("shopping:set_store") + "?group_by=category",
            {"store_id": str(kroger_store.id)},
        )
        assert resp.status_code == 200
        s_list.refresh_from_db()
        assert s_list.active_store == kroger_store

        # 2. In Category view, Cheddar Cheese has actual aisle "Aisle 36 Bay 2", Baguette is blank (no location tag)
        content = resp.content.decode("utf-8")
        assert "📍 Aisle 36 Bay 2" in content
        assert item1.get_effective_aisle() == "Aisle 36"
        assert item1.effective_bay == "2"
        assert item1.effective_location_display == "Aisle 36 Bay 2"
        # Effective aisle for unmapped item must be blank, not "Bakery"
        assert item2.get_effective_aisle() == ""
        assert item2.effective_location_display == ""

        # 3. In Aisle view, Cheddar Cheese appears under "Aisle 36", Baguette appears under "Other"
        aisle_resp = client.get(reverse("shopping:list") + "?group_by=aisle")
        assert aisle_resp.status_code == 200
        aisle_content = aisle_resp.content.decode("utf-8")
        assert "Aisle 36" in aisle_content
        assert "📍 Bay 2" in aisle_content
        assert "Other" in aisle_content
        # Ensure categories are not shown as aisle section headers
        assert '<h3 class="font-black text-sm tracking-wider uppercase text-gray-950 select-none">\n                                Dairy' not in aisle_content
        assert '<h3 class="font-black text-sm tracking-wider uppercase text-gray-950 select-none">\n                                Bakery' not in aisle_content


@pytest.mark.django_db
def test_perimeter_items_produce_and_meat_display_aisle_and_bay():
    """
    Verify that perimeter department items (Produce, Meat) with matching categories
    are NOT suppressed, and show both department/aisle and bay when available.
    """
    store = StoreLocation.objects.create(name="King Soopers Perimeter", chain="kroger")
    s_list = ShoppingList.objects.create(name="Perimeter List", active_store=store)

    carrots = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Carrots",
        amount=Decimal("1.00"),
        category="produce",
        status=ItemStatus.NEED,
    )
    beef = ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Ground Beef",
        amount=Decimal("1.00"),
        category="meat",
        status=ItemStatus.NEED,
    )

    StoreItemAisle.objects.create(
        store=store,
        item_name_normalized="carrot",
        aisle_name="PRODUCE",
        bay_number="7",
        source="api",
    )
    StoreItemAisle.objects.create(
        store=store,
        item_name_normalized="ground beef",
        aisle_name="MEAT",
        bay_number="14",
        source="api",
    )

    assert carrots.get_effective_aisle() == "Produce"
    assert carrots.effective_bay == "7"
    assert carrots.effective_location_display == "Produce Bay 7"

    assert beef.get_effective_aisle() == "Meat"
    assert beef.effective_bay == "14"
    assert beef.effective_location_display == "Meat Bay 14"


