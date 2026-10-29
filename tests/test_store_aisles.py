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

    # Test POST to find_nearest_store endpoint returns modal with stores and map
    response = client.post(
        reverse("shopping:nearest_store"),
        {
            "latitude": "39.753",
            "longitude": "-105.000",
        },
    )
    assert response.status_code == 200
    assert b"Store Selector & Map Picker" in response.content
    assert b"store-picker-map" in response.content
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
def test_store_search_by_text_query(client):
    """
    Test typing a store name or city in find_nearest_store filters and matches stores.
    """
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    from apps.core.models import Workspace

    User = get_user_model()
    user = User.objects.create_user(username="search_tester")
    ws = Workspace.objects.create(name="Search WS", owner=user)
    ShoppingList.objects.create(name="Search List", workspace=ws, owner=user)
    client.force_login(user)

    resp = client.post(
        reverse("shopping:nearest_store"),
        {"query": "Safeway"},
    )
    assert resp.status_code == 200
    assert b"Store Selector & Map Picker" in resp.content
    assert b"Safeway" in resp.content
    assert b"store-picker-map" in resp.content

    # Dynamic search with results_only=true returns partial without re-rendering map container
    partial_resp = client.post(
        reverse("shopping:nearest_store"),
        {"query": "Safeway", "results_only": "true"},
    )
    assert partial_resp.status_code == 200
    assert b"Safeway" in partial_resp.content
    assert b"store-picker-map" not in partial_resp.content
    assert b"store-picker-update-data" in partial_resp.content


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


def test_normalize_search_term_inverted_comma_names():
    """
    Test that inverted comma names (e.g. 'apples, green', 'beans, fresh')
    are properly normalized into natural search terms ('green apple', 'fresh bean').
    """
    from apps.shopping.services.store_service import normalize_search_term

    assert normalize_search_term("apples, green") == "green apple"
    assert normalize_search_term("beans, fresh") == "fresh bean"
    assert normalize_search_term("onions, red") == "red onion"
    assert normalize_search_term("carrots") == "carrot"
    assert normalize_search_term("green apple") == "green apple"


@pytest.mark.django_db
def test_kroger_api_client_finds_aisle_in_subsequent_products(monkeypatch):
    """
    Test that when the first returned product has empty aisleLocations (common with bulk produce),
    lookup_product_aisle continues checking up to 5 products to find the aisle and bay.
    """
    import json
    from unittest.mock import MagicMock, patch

    from apps.shopping.services.store_service import kroger_client

    mock_response_data = {
        "data": [
            {
                "description": "Organic Bulk Kale",
                "aisleLocations": [],  # First product has no planogram location
            },
            {
                "description": "Kroger Chopped Kale Bagged Salad",
                "aisleLocations": [
                    {
                        "description": "PRODUCE",
                        "bayNumber": "11",
                        "number": "105",
                        "sequenceNumber": "15",
                    }
                ],
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(kroger_client, "get_access_token", return_value="fake_token"), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        res = kroger_client.lookup_product_aisle("62000042", "kale")
        assert res is not None
        assert res["aisle_name"] == "PRODUCE"
        assert res["bay_number"] == "11"
        assert res["sequence_order"] == 15


@pytest.mark.django_db
def test_warm_store_aisles_streams_live_updates_per_item():
    """
    Verify that _warm_store_aisles_async streams live WebSocket broadcasts as each
    item's aisle is resolved, allowing the browser to refresh items and sorting in real time.
    """
    from unittest.mock import patch

    from apps.shopping.services.store_service import kroger_client
    from apps.shopping.views import _warm_store_aisles_async

    store = StoreLocation.objects.create(
        name="King Soopers Streaming",
        chain="kroger",
        external_store_id="62000090",
    )
    s_list = ShoppingList.objects.create(name="Streaming List", active_store=store)

    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Organic Kale",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
    )
    ShoppingListItem.objects.create(
        shopping_list=s_list,
        name="Ground Beef",
        amount=Decimal("1.00"),
        status=ItemStatus.NEED,
    )

    def mock_resolve(target_store, item_name, category=None):
        if "kale" in item_name.lower():
            StoreItemAisle.objects.create(
                store=target_store,
                item_name_normalized="organic kale",
                aisle_name="Produce",
                bay_number="11",
                source="api",
            )
            return {"aisle_name": "Produce", "bay_number": "11"}
        elif "beef" in item_name.lower():
            StoreItemAisle.objects.create(
                store=target_store,
                item_name_normalized="ground beef",
                aisle_name="Meat",
                bay_number="1",
                source="api",
            )
            return {"aisle_name": "Meat", "bay_number": "1"}
        return None

    broadcast_calls = []

    def mock_broadcast(**kwargs):
        broadcast_calls.append(kwargs)

    with patch.object(type(kroger_client), "is_configured", True), \
         patch("apps.shopping.views.resolve_store_aisle", side_effect=mock_resolve), \
         patch("apps.shopping.views.broadcast_shopping_list_update", side_effect=mock_broadcast):
        _warm_store_aisles_async(s_list, sync=True)

    # Must have 2 per-item streaming broadcasts (toast_message="") + 1 final completion broadcast
    assert len(broadcast_calls) == 3

    # Per-item updates: silent toasts to prevent popup spam, empty sender_client_id so all tabs refresh
    assert broadcast_calls[0]["toast_message"] == ""
    assert broadcast_calls[0]["sender_client_id"] == ""
    assert broadcast_calls[1]["toast_message"] == ""
    assert broadcast_calls[1]["sender_client_id"] == ""

    # Final completion update: summary toast
    assert "Aisles updated for King Soopers Streaming" in broadcast_calls[2]["toast_message"]


def test_get_ingredient_search_candidates():
    """
    Test that culinary modifiers, parentheticals, comma clauses, and quantities
    are stripped down to specific and general candidate terms.
    """
    from apps.shopping.services.store_service import get_ingredient_search_candidates

    pepper_cands = get_ingredient_search_candidates("freshly ground black pepper")
    assert "black pepper" in pepper_cands
    assert "pepper" in pepper_cands

    garlic_cands1 = get_ingredient_search_candidates("cloves garlic, minced")
    assert "garlic" in garlic_cands1

    garlic_cands2 = get_ingredient_search_candidates("garlic cloves (minced)")
    assert "garlic" in garlic_cands2

    onion_cands = get_ingredient_search_candidates("diced yellow onion")
    assert "yellow onion" in onion_cands
    assert "onion" in onion_cands

    cilantro_cands = get_ingredient_search_candidates("fresh cilantro leafe")
    assert "cilantro" in cilantro_cands

    coriander_cands = get_ingredient_search_candidates("coriander powder")
    assert "coriander" in coriander_cands

    apple_cands = get_ingredient_search_candidates("apples, green")
    assert "green apple" in apple_cands

    bean_cands = get_ingredient_search_candidates("2 cans black beans")
    assert "black bean" in bean_cands

    chicken_cands = get_ingredient_search_candidates("boneless skinless chicken breast")
    assert "chicken breast" in chicken_cands

    oil_cands = get_ingredient_search_candidates("extra virgin olive oil")
    assert "olive oil" in oil_cands


@pytest.mark.django_db
def test_resolve_store_aisle_cleans_culinary_terms_and_prevents_negative_db_cache():
    """
    Verify that resolve_store_aisle tries candidate terms when raw culinary term yields no results,
    persists resolved aisles for both candidate and raw term, and NEVER saves empty aisle strings.
    """
    from unittest.mock import patch
    from apps.shopping.services.store_service import kroger_client

    store = StoreLocation.objects.create(
        name="King Soopers #62000111 (Fresh Fare)",
        chain="kroger",
        external_store_id="62000111",
    )

    def mock_lookup(loc_id, term):
        if term == "black pepper":
            return {"aisle_name": "AISLE 3", "bay_number": "24", "sequence_order": 100}
        # Raw term returns None
        return None

    with patch.object(type(kroger_client), "is_configured", True), \
         patch.object(kroger_client, "lookup_product_aisle", side_effect=mock_lookup):

        result = resolve_store_aisle(store, "freshly ground black pepper")
        assert result is not None
        assert result["aisle_name"] == "AISLE 3"
        assert result["bay_number"] == "24"

        # Check DB mappings
        orig_rec = StoreItemAisle.objects.filter(store=store, item_name_normalized="freshly ground black pepper").first()
        cand_rec = StoreItemAisle.objects.filter(store=store, item_name_normalized="black pepper").first()
        assert orig_rec is not None and orig_rec.aisle_name == "AISLE 3"
        assert cand_rec is not None and cand_rec.aisle_name == "AISLE 3"

        # Now test an item that is truly unfindable
        unfound = resolve_store_aisle(store, "completely nonexistent ingredient xyz")
        assert unfound is None

        # Verify NO empty string records were created in StoreItemAisle
        empty_records = StoreItemAisle.objects.filter(store=store, aisle_name="")
        assert empty_records.count() == 0


@pytest.mark.django_db
def test_resolve_store_aisle_cross_store_universal_department_fallback():
    """
    Verify that if a specific store cannot resolve a perimeter item via live API,
    it falls back to universal perimeter departments (Produce, Meat, Dairy, etc.)
    learned from other Kroger stores.
    """
    from unittest.mock import patch
    from apps.shopping.services.store_service import kroger_client

    store1 = StoreLocation.objects.create(
        name="King Soopers #62000001",
        chain="kroger",
        external_store_id="62000001",
    )
    store2 = StoreLocation.objects.create(
        name="King Soopers #62000111",
        chain="kroger",
        external_store_id="62000111",
    )

    # Store 1 has cilantro mapped to PRODUCE
    StoreItemAisle.objects.create(
        store=store1,
        item_name_normalized="cilantro",
        aisle_name="PRODUCE",
        sequence_order=10,
        source="api",
    )

    with patch.object(type(kroger_client), "is_configured", True), \
         patch.object(kroger_client, "lookup_product_aisle", return_value=None):

        # Store 2 has no API match, but should fall back to universal PRODUCE department
        result = resolve_store_aisle(store2, "fresh cilantro leafe")
        assert result is not None
        assert result["aisle_name"] == "PRODUCE"

        # Verify Store 2 now has the mapping cached
        s2_rec = StoreItemAisle.objects.filter(store=store2, item_name_normalized="fresh cilantro leafe").first()
        assert s2_rec is not None and s2_rec.aisle_name == "PRODUCE"


@pytest.mark.django_db
def test_store_switching_aisle_resolution_flow(client):
    """
    Test the complete user scenario:
    1. Select store #62000111 and add an ingredient.
    2. Switch to another store (#62000001) -> aisles populate.
    3. Switch back to #62000111 -> aisles remain populated and never locked out.
    """
    from unittest.mock import patch
    from django.contrib.auth import get_user_model
    from django.urls import reverse
    from apps.core.models import Workspace
    from apps.shopping.services.store_service import kroger_client

    User = get_user_model()
    user = User.objects.create_user(username="switch_tester")
    ws = Workspace.objects.create(name="Switch WS", owner=user)
    s_list = ShoppingList.objects.create(name="Switch List", workspace=ws, owner=user)
    client.force_login(user)

    store_111 = StoreLocation.objects.create(
        name="King Soopers #62000111",
        chain="kroger",
        external_store_id="62000111",
    )
    store_001 = StoreLocation.objects.create(
        name="King Soopers #62000001",
        chain="kroger",
        external_store_id="62000001",
    )

    def mock_lookup(loc_id, term):
        if loc_id == "62000111" and "garlic" in term:
            return {"aisle_name": "Produce Table 3", "bay_number": "2", "sequence_order": 10}
        elif loc_id == "62000001" and "garlic" in term:
            return {"aisle_name": "Produce", "bay_number": "5", "sequence_order": 10}
        return None

    with patch.object(type(kroger_client), "is_configured", True), \
         patch.object(kroger_client, "lookup_product_aisle", side_effect=mock_lookup):

        # Step 1: Select store #62000111
        resp = client.post(reverse("shopping:set_store"), {"store_id": str(store_111.id)})
        assert resp.status_code == 200

        # Add ingredient with culinary descriptor
        add_resp = client.post(
            reverse("shopping:add_item"),
            {"name": "cloves garlic, minced", "amount": "2", "amount_unit": "cloves"},
        )
        assert add_resp.status_code == 200

        item = ShoppingListItem.objects.filter(shopping_list=s_list, name="cloves garlic, minced").first()
        assert item is not None
        assert item.get_effective_aisle(store_111) == "Produce Table 3"
        assert item.get_effective_bay(store_111) == "2"

        # Step 2: Switch to store #62000001
        switch1 = client.post(reverse("shopping:set_store"), {"store_id": str(store_001.id)})
        assert switch1.status_code == 200
        assert item.get_effective_aisle(store_001) == "Produce"

        # Step 3: Switch back to store #62000111
        switch2 = client.post(reverse("shopping:set_store"), {"store_id": str(store_111.id)})
        assert switch2.status_code == 200
        assert item.get_effective_aisle(store_111) == "Produce Table 3"
        assert item.get_effective_bay(store_111) == "2"




