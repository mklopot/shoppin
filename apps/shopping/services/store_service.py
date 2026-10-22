"""
Store location, walking sequence, and aisle mapping service.

Integrates with the official Kroger Developer API for product aisle lookups
and provides standard walking-order sequences through supermarket departments.
"""

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
    Compute a natural sorting key for an aisle name to ensure logical walking order.

    Order hierarchy:
    1. Fresh perimeter entrance departments (Produce, Floral, Bakery, Deli, Meat) -> sequence 10-40.
    2. Numbered grocery aisles in numeric order (Aisle 1, Aisle 2, ..., Aisle 14, ...) -> sequence 100 + num.
    3. Cold perimeter departments (Dairy, Frozen, Ice Cream) -> sequence 200+.
    4. General / Other fallback -> sequence 300+.

    Args:
        aisle_name: Display aisle string (e.g. 'Aisle 14', 'Produce').

    Returns:
        tuple of (phase_tier, numeric_aisle_or_zero, lowercase_aisle_string).
    """
    clean_name = (aisle_name or "").strip().lower()

    # Fresh perimeter (entrance departments)
    if any(keyword in clean_name for keyword in ["produce", "fruit", "floral", "entrance"]):
        return (10, 0, clean_name)
    if any(keyword in clean_name for keyword in ["bakery", "bread"]):
        return (20, 0, clean_name)
    if any(keyword in clean_name for keyword in ["deli", "prepared", "sandwich"]):
        return (30, 0, clean_name)
    if any(keyword in clean_name for keyword in ["meat", "seafood", "butcher", "fish"]):
        return (40, 0, clean_name)

    # Numbered grocery aisles: e.g. "Aisle 1", "Aisle 14", "Aisle 35"
    number_match = re.search(r"\d+", clean_name)
    if number_match:
        return (100, int(number_match.group(0)), clean_name)

    # Cold perimeter departments
    if any(keyword in clean_name for keyword in ["frozen", "freezer", "ice cream"]):
        return (200, 0, clean_name)
    if any(keyword in clean_name for keyword in ["dairy", "milk", "cheese", "eggs"]):
        return (210, 0, clean_name)

    return (300, 0, clean_name)


def haversine_distance(latitude1: float, longitude1: float, latitude2: float, longitude2: float) -> float:
    """
    Calculate the great-circle distance between two geographic coordinates in miles.

    Args:
        latitude1: Latitude of point 1.
        longitude1: Longitude of point 1.
        latitude2: Latitude of point 2.
        longitude2: Longitude of point 2.

    Returns:
        Distance in miles rounded to 2 decimal places.
    """
    earth_radius_miles = 3958.8
    delta_latitude = math.radians(latitude2 - latitude1)
    delta_longitude = math.radians(longitude2 - longitude1)
    haversine_formula = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(math.radians(latitude1))
        * math.cos(math.radians(latitude2))
        * math.sin(delta_longitude / 2) ** 2
    )
    central_angle = 2 * math.atan2(math.sqrt(haversine_formula), math.sqrt(1 - haversine_formula))
    return round(earth_radius_miles * central_angle, 2)


def get_nearest_stores(latitude: float, longitude: float, limit: int = 5) -> list[dict[str, Any]]:
    """
    Find the nearest StoreLocation records to the given coordinates.

    Args:
        latitude: Target latitude coordinate.
        longitude: Target longitude coordinate.
        limit: Maximum number of closest stores to return.

    Returns:
        List of dicts containing store instance and distance_miles.
    """
    stores = StoreLocation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    store_results = []
    for store in stores:
        distance_miles = haversine_distance(latitude, longitude, store.latitude, store.longitude)
        store_results.append({
            "store": store,
            "distance_miles": distance_miles,
        })
    store_results.sort(key=lambda result: result["distance_miles"])
    return store_results[:limit]


class KrogerAPIClient:
    """
    Client for the official Kroger Developer API.

    Handles OAuth2 Client Credentials token negotiation and product aisle lookups.
    Reference: https://developer.kroger.com/reference/
    """
    TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
    PRODUCTS_URL = "https://api.kroger.com/v1/products"

    def __init__(self) -> None:
        """Initialize the Kroger API client from environment variables."""
        self.client_id = os.getenv("KROGER_CLIENT_ID", "")
        self.client_secret = os.getenv("KROGER_CLIENT_SECRET", "")
        self._cached_token: str | None = None

    @property
    def is_configured(self) -> bool:
        """Return True if API credentials are provided in the environment."""
        return bool(self.client_id and self.client_secret)

    def get_access_token(self) -> str | None:
        """
        Request or return a cached OAuth2 access token for product lookup requests.

        Returns:
            Bearer access token string, or None if configuration is missing or call fails.
        """
        if not self.is_configured:
            return None
        if self._cached_token:
            return self._cached_token

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        post_data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "product.compact",
        }).encode()
        request = urllib.request.Request(
            self.TOKEN_URL,
            data=post_data,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                response_data = json.loads(response.read().decode())
                self._cached_token = response_data.get("access_token")
                return self._cached_token
        except Exception as error:
            logger.warning(f"Failed to fetch Kroger access token: {error}")
            return None

    def lookup_product_aisle(self, location_id: str, product_term: str) -> dict[str, Any] | None:
        """
        Query the Kroger API for a product term at a specific store locationId.

        Args:
            location_id: Kroger store location identifier (e.g. '01400943').
            product_term: The product name or search term.

        Returns:
            Dict containing aisle_name, bay_number, sequence_order, or None if not found.
        """
        token = self.get_access_token()
        if not token:
            return None

        query_params = urllib.parse.urlencode({
            "filter.term": product_term,
            "filter.locationId": location_id,
            "filter.limit": 1,
        })
        url = f"{self.PRODUCTS_URL}?{query_params}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode())
                products = data.get("data", [])
                if not products:
                    return None

                first_product = products[0]
                aisle_locations = first_product.get("aisleLocations", [])
                if not aisle_locations:
                    return None

                first_location = aisle_locations[0]
                return {
                    "aisle_name": first_location.get("description") or f"Aisle {first_location.get('number', '')}".strip(),
                    "bay_number": first_location.get("bayNumber", ""),
                    "sequence_order": int(first_location.get("sequenceNumber", 100)),
                }
        except Exception as error:
            logger.warning(f"Kroger API lookup failed for '{product_term}' at location {location_id}: {error}")
            return None


kroger_client = KrogerAPIClient()


def resolve_store_aisle(store: StoreLocation, item_name: str) -> dict[str, Any]:
    """
    Resolve and cache the physical store aisle for a grocery item.

    Resolution strategy:
    1. Check the local StoreItemAisle database cache.
    2. If missing and store is a Kroger location with API enabled, query live Kroger API and cache result.
    3. Fallback to category-based walking order from the categorizer engine.

    Args:
        store: Target StoreLocation instance.
        item_name: The name of the grocery item.

    Returns:
        Dict with aisle_name, bay_number, sequence_order, and source ('api', 'manual', 'default').
    """
    clean_name = inflection.singularize(item_name.strip().lower())

    # 1. Check local database cache
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
    predicted_category = categorizer.get_category(clean_name)
    sequence_order = DEPARTMENT_ORDER.get(predicted_category.lower(), 200)
    display_name = predicted_category.title()

    # Cache as default so future queries hit DB directly
    StoreItemAisle.objects.create(
        store=store,
        item_name_normalized=clean_name,
        aisle_name=display_name,
        bay_number="",
        sequence_order=sequence_order,
        source="default",
    )

    return {
        "aisle_name": display_name,
        "bay_number": "",
        "sequence_order": sequence_order,
        "source": "default",
    }


def get_known_categories() -> list[str]:
    """
    Return a sorted, unique list of all known grocery categories across index, defaults, and items.

    Returns:
        Alphabetically sorted list of title-cased category names.
    """
    from apps.shopping.models import ShoppingListItem

    categories: set[str] = set()
    for category in categorizer.categories_index.keys():
        if category:
            categories.add(category.title())
    for category in DEPARTMENT_ORDER.keys():
        if category:
            categories.add(category.title())
    for category in ShoppingListItem.objects.exclude(category="").values_list("category", flat=True).distinct():
        if category:
            categories.add(category.title())
    return sorted(list(categories))


def get_known_aisles(store: StoreLocation | None = None) -> list[str]:
    """
    Return a natural-walking-ordered list of known aisles for a store or the entire catalog.

    Args:
        store: Optional store to filter known aisle names by.

    Returns:
        List of aisle strings sorted by supermarket perimeter / aisle order.
    """
    from apps.shopping.models import ShoppingListItem

    aisles_set: set[str] = set()
    if store:
        for aisle in StoreItemAisle.objects.filter(store=store).exclude(aisle_name="").values_list("aisle_name", flat=True).distinct():
            if aisle:
                aisles_set.add(aisle.strip())

    for aisle in StoreItemAisle.objects.exclude(aisle_name="").values_list("aisle_name", flat=True).distinct():
        if aisle:
            aisles_set.add(aisle.strip())

    for aisle in ShoppingListItem.objects.exclude(aisle="").values_list("aisle", flat=True).distinct():
        if aisle:
            aisles_set.add(aisle.strip())

    common_departments = [
        "Produce", "Bakery", "Deli", "Meat", "Seafood", "Dairy", "Frozen", "Pantry"
    ]
    for department in common_departments:
        aisles_set.add(department)

    return sorted(list(aisles_set), key=get_aisle_sort_key)
