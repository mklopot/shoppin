import base64
import json
import logging
import math
import os
import re
import urllib.parse
import urllib.request
from typing import Any

import inflection

from apps.core.categorizer import categorizer
from apps.shopping.models import StoreItemAisle, StoreLocation

logger = logging.getLogger(__name__)

# Standard supermarket walking order fallback (department -> sequence order)
DEPARTMENT_ORDER = {
    "produce": 10,
    "bakery": 20,
    "deli": 30,
    "meat": 40,
    "seafood": 45,
    "pantry": 50,
    "canned vegetables": 55,
    "canned fruit": 56,
    "canned goods": 57,
    "pasta and grains": 60,
    "international foods": 65,
    "mexican food": 66,
    "spices": 70,
    "oil": 72,
    "condiments": 75,
    "snacks": 80,
    "energy bars": 82,
    "tea and coffee": 85,
    "beverages": 88,
    "frozen": 90,
    "eggs and dairy": 95,
    "dairy": 95,
    "cheese": 96,
    "personal care": 110,
    "cleaning": 120,
    "other": 200,
}


def get_aisle_sort_key(aisle_name: str) -> tuple[int, int, str]:
    """
    Computes a natural sorting key for an aisle name to ensure logical walking order:
    1. Early perimeter fresh departments (Produce, Floral, Bakery, Deli, Meat) -> sequence 10-40
    2. Numbered grocery aisles in numeric order (Aisle 1, Aisle 2, ..., Aisle 14, ..., Aisle 35) -> sequence 100 + num
    3. Cold perimeter departments (Dairy, Frozen, Ice Cream) -> sequence 200+
    4. General / Other -> sequence 300+
    """
    clean = (aisle_name or "").strip().lower()

    # Fresh perimeter (entrance departments)
    if any(k in clean for k in ["produce", "fruit", "floral", "entrance"]):
        return (10, 0, clean)
    if any(k in clean for k in ["bakery", "bread"]):
        return (20, 0, clean)
    if any(k in clean for k in ["deli", "prepared", "sandwich"]):
        return (30, 0, clean)
    if any(k in clean for k in ["meat", "seafood", "butcher", "fish"]):
        return (40, 0, clean)

    # Numbered grocery aisles: e.g. "Aisle 1", "Aisle 14", "Aisle 35"
    num_match = re.search(r"\d+", clean)
    if num_match:
        return (100, int(num_match.group(0)), clean)

    # Cold perimeter departments
    if any(k in clean for k in ["frozen", "freezer", "ice cream"]):
        return (200, 0, clean)
    if any(k in clean for k in ["dairy", "milk", "cheese", "eggs"]):
        return (210, 0, clean)

    return (300, 0, clean)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on the Earth (in miles).
    """
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


def get_nearest_stores(lat: float, lon: float, limit: int = 5) -> list[dict[str, Any]]:
    """
    Finds nearest StoreLocation records to the given coordinates.
    """
    stores = StoreLocation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    results = []
    for store in stores:
        dist = haversine_distance(lat, lon, store.latitude, store.longitude)
        results.append({
            "store": store,
            "distance_miles": dist,
        })
    results.sort(key=lambda x: x["distance_miles"])
    return results[:limit]


class KrogerAPIClient:
    """
    Client for the official Kroger Developer API.
    Docs: https://developer.kroger.com/reference/
    """
    TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
    PRODUCTS_URL = "https://api.kroger.com/v1/products"

    def __init__(self):
        self.client_id = os.getenv("KROGER_CLIENT_ID", "")
        self.client_secret = os.getenv("KROGER_CLIENT_SECRET", "")
        self._cached_token = None

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_access_token(self) -> str | None:
        if not self.is_configured:
            return None
        if self._cached_token:
            return self._cached_token

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "product.compact"}).encode()
        req = urllib.request.Request(
            self.TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                res_data = json.loads(resp.read().decode())
                self._cached_token = res_data.get("access_token")
                return self._cached_token
        except Exception as e:
            logger.warning(f"Failed to fetch Kroger access token: {e}")
            return None

    def lookup_product_aisle(self, location_id: str, product_term: str) -> dict[str, Any] | None:
        """
        Query Kroger API for product term and locationId to extract aisle location.
        """
        token = self.get_access_token()
        if not token:
            return None

        params = urllib.parse.urlencode({
            "filter.term": product_term,
            "filter.locationId": location_id,
            "filter.limit": 1,
        })
        url = f"{self.PRODUCTS_URL}?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                products = data.get("data", [])
                if not products:
                    return None

                first_prod = products[0]
                aisle_locations = first_prod.get("aisleLocations", [])
                if not aisle_locations:
                    return None

                aisle = aisle_locations[0]
                return {
                    "aisle_name": aisle.get("description") or f"Aisle {aisle.get('number', '')}".strip(),
                    "bay_number": aisle.get("bayNumber", ""),
                    "sequence_order": int(aisle.get("sequenceNumber", 100)),
                }
        except Exception as e:
            logger.warning(f"Kroger API lookup failed for '{product_term}' at location {location_id}: {e}")
            return None


kroger_client = KrogerAPIClient()


def resolve_store_aisle(store: StoreLocation, item_name: str) -> dict[str, Any]:
    """
    Resolves aisle for an item at a specific store:
    1. Checks local StoreItemAisle cache.
    2. If not found and store is Kroger, queries Kroger API and caches result.
    3. If not found, falls back to standard department walking order.
    """
    clean_name = inflection.singularize(item_name.strip().lower())

    # 1. Check local cache
    cached = StoreItemAisle.objects.filter(store=store, item_name_normalized=clean_name).first()
    if cached:
        return {
            "aisle_name": cached.aisle_name,
            "bay_number": cached.bay_number,
            "sequence_order": cached.sequence_order,
            "source": cached.source,
        }

    # 2. Query Kroger API if applicable
    if store.chain == "kroger" and store.external_store_id and kroger_client.is_configured:
        api_result = kroger_client.lookup_product_aisle(store.external_store_id, clean_name)
        if api_result:
            StoreItemAisle.objects.create(
                store=store,
                item_name_normalized=clean_name,
                aisle_name=api_result["aisle_name"],
                bay_number=api_result.get("bay_number", ""),
                sequence_order=api_result.get("sequence_order", 100),
                source="api",
            )
            return {
                "aisle_name": api_result["aisle_name"],
                "bay_number": api_result.get("bay_number", ""),
                "sequence_order": api_result.get("sequence_order", 100),
                "source": "api",
            }

    # 3. Department / Category fallback
    cat = categorizer.get_category(clean_name)
    seq = DEPARTMENT_ORDER.get(cat.lower(), 200)
    display_name = cat.title()

    # Cache as default so queries are instant
    StoreItemAisle.objects.create(
        store=store,
        item_name_normalized=clean_name,
        aisle_name=display_name,
        bay_number="",
        sequence_order=seq,
        source="default",
    )

    return {
        "aisle_name": display_name,
        "bay_number": "",
        "sequence_order": seq,
        "source": "default",
    }


def get_known_categories() -> list[str]:
    """Return sorted, unique list of all known categories."""
    from apps.shopping.models import ShoppingListItem

    cats = set()
    for c in categorizer.categories_index.keys():
        if c:
            cats.add(c.title())
    for c in DEPARTMENT_ORDER.keys():
        if c:
            cats.add(c.title())
    for c in ShoppingListItem.objects.exclude(category="").values_list("category", flat=True).distinct():
        if c:
            cats.add(c.title())
    return sorted(list(cats))


def get_known_aisles(store: StoreLocation | None = None) -> list[str]:
    """Return sorted, unique list of all known aisles for the active store or system."""
    from apps.shopping.models import ShoppingListItem

    aisles = set()
    if store:
        for a in StoreItemAisle.objects.filter(store=store).exclude(aisle_name="").values_list("aisle_name", flat=True).distinct():
            if a:
                aisles.add(a.strip())

    for a in StoreItemAisle.objects.exclude(aisle_name="").values_list("aisle_name", flat=True).distinct():
        if a:
            aisles.add(a.strip())

    for a in ShoppingListItem.objects.exclude(aisle="").values_list("aisle", flat=True).distinct():
        if a:
            aisles.add(a.strip())

    common_departments = [
        "Produce", "Bakery", "Deli", "Meat", "Seafood", "Dairy", "Frozen", "Pantry"
    ]
    for d in common_departments:
        aisles.add(d)

    return sorted(list(aisles), key=get_aisle_sort_key)
