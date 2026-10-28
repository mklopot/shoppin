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


def discover_nearby_stores_osm(latitude: float, longitude: float) -> list[StoreLocation]:
    """
    Dynamically discover supermarkets near coordinates via OpenStreetMap Nominatim.
    Ingests discovered locations into StoreLocation with chain heuristic.
    """
    delta = 0.15
    url = (
        f"https://nominatim.openstreetmap.org/search?format=json"
        f"&q=supermarket&bounded=1&viewbox={longitude - delta},{latitude + delta},{longitude + delta},{latitude - delta}"
        f"&limit=15&addressdetails=1"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ShoppinApp-StoreLocator/2.0"},
    )
    created_stores = []
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode())
            for item in data:
                addr = item.get("address", {})
                raw_name = (
                    item.get("namedetails", {}).get("name")
                    or addr.get("supermarket")
                    or item.get("display_name", "").split(",")[0].strip()
                )
                if not raw_name:
                    continue
                road = addr.get("road", "")
                house = addr.get("house_number", "")
                street = f"{house} {road}".strip() or addr.get("suburb", "")
                city = addr.get("city") or addr.get("town") or addr.get("suburb", "")
                state = addr.get("state", "")
                postcode = addr.get("postcode", "")
                lat = float(item["lat"])
                lon = float(item["lon"])

                name_lower = raw_name.lower()
                if any(k in name_lower for k in ["kroger", "king soopers", "ralphs", "fred meyer"]):
                    chain = "kroger"
                elif any(k in name_lower for k in ["safeway", "albertsons", "vons"]):
                    chain = "safeway"
                elif "whole foods" in name_lower:
                    chain = "whole_foods"
                elif "trader joe" in name_lower:
                    chain = "trader_joes"
                elif "sprouts" in name_lower:
                    chain = "sprouts"
                elif "target" in name_lower:
                    chain = "target"
                else:
                    chain = "other"

                store_obj, _ = StoreLocation.objects.get_or_create(
                    name=raw_name,
                    latitude=lat,
                    longitude=lon,
                    defaults={
                        "chain": chain,
                        "address": street,
                        "city": city,
                        "state": state,
                        "zip_code": postcode,
                    },
                )
                created_stores.append(store_obj)
    except Exception as error:
        logger.warning(f"Dynamic store discovery failed or timed out: {error}")

    return created_stores


def _collect_deduped_store_distances(latitude: float, longitude: float) -> list[dict[str, Any]]:
    """
    Collect all valid stores with distances, strictly deduplicating by chain + external_id/address/coords.
    """
    stores = StoreLocation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    store_results = []
    seen_identities: set[str] = set()

    for store in stores:
        if store.chain and store.external_store_id:
            ident = f"{store.chain}:{store.external_store_id}"
        elif store.address:
            ident = f"{store.chain}:{store.address.lower().strip()}"
        else:
            ident = f"{store.chain}:{round(store.latitude, 3)}:{round(store.longitude, 3)}"

        if ident in seen_identities:
            continue
        seen_identities.add(ident)

        distance_miles = haversine_distance(latitude, longitude, store.latitude, store.longitude)
        store_results.append({
            "store": store,
            "distance_miles": distance_miles,
        })

    store_results.sort(key=lambda result: result["distance_miles"])
    return store_results


def get_nearest_stores(latitude: float, longitude: float, limit: int = 5) -> list[dict[str, Any]]:
    """
    Find the nearest StoreLocation records to the given coordinates,
    strictly deduplicating identical physical locations.
    If the closest store in the database is more than 25 miles away,
    attempts dynamic discovery via OpenStreetMap Nominatim.

    Args:
        latitude: Target latitude coordinate.
        longitude: Target longitude coordinate.
        limit: Maximum number of closest stores to return.

    Returns:
        List of dicts containing store instance and distance_miles.
    """
    store_results = _collect_deduped_store_distances(latitude, longitude)

    # If all existing stores are far away (> 25 miles), attempt dynamic discovery
    if not store_results or store_results[0]["distance_miles"] > 25.0:
        discovered = discover_nearby_stores_osm(latitude, longitude)
        if discovered:
            store_results = _collect_deduped_store_distances(latitude, longitude)

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
        self._cached_token: str | None = None

    @property
    def client_id(self) -> str:
        """Resolve client ID dynamically from environment or settings."""
        from django.conf import settings
        val = (os.getenv("KROGER_CLIENT_ID", "") or getattr(settings, "KROGER_CLIENT_ID", "")).strip()
        if not val:
            from dotenv import load_dotenv
            load_dotenv()
            val = os.getenv("KROGER_CLIENT_ID", "").strip()
        return val

    @property
    def client_secret(self) -> str:
        """Resolve client secret dynamically from environment or settings."""
        from django.conf import settings
        val = (os.getenv("KROGER_CLIENT_SECRET", "") or getattr(settings, "KROGER_CLIENT_SECRET", "")).strip()
        if not val:
            from dotenv import load_dotenv
            load_dotenv()
            val = os.getenv("KROGER_CLIENT_SECRET", "").strip()
        return val

    @property
    def is_configured(self) -> bool:
        """Return True if both client_id and client_secret are provided."""
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

        # Normalize legacy 014 division IDs to Colorado 620 division IDs
        aliases = {
            "01400018": "62000124",
            "01400035": "62000001",
            "01400012": "62000090",
        }
        clean_loc = aliases.get(location_id, location_id)
        if clean_loc.startswith("014"):
            clean_loc = "620" + clean_loc[3:]

        query_params = urllib.parse.urlencode({
            "filter.term": product_term,
            "filter.locationId": clean_loc,
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
                desc = (first_location.get("description") or "").strip()
                num = (first_location.get("number") or "").strip()
                aisle_name = desc or (f"Aisle {num}" if num else "")
                if not aisle_name:
                    return None

                seq_val = first_location.get("sequenceNumber")
                try:
                    sequence_order = int(seq_val) if seq_val is not None else 100
                except (ValueError, TypeError):
                    sequence_order = 100

                return {
                    "aisle_name": aisle_name,
                    "bay_number": (first_location.get("bayNumber") or "").strip(),
                    "sequence_order": sequence_order,
                }
        except Exception as error:
            logger.warning(f"Kroger API lookup failed for '{product_term}' at location {location_id}: {error}")
            return None


kroger_client = KrogerAPIClient()


def _save_store_item_aisle(
    store: StoreLocation,
    item_name_normalized: str,
    aisle_name: str,
    bay_number: str = "",
    sequence_order: int = 100,
    source: str = "api",
) -> StoreItemAisle | None:
    """
    Safely persist or update a StoreItemAisle record without using select_for_update,
    handling SQLite concurrency gracefully with exponential backoff retries.
    """
    import time
    for attempt in range(4):
        try:
            record = StoreItemAisle.objects.filter(
                store=store,
                item_name_normalized=item_name_normalized,
            ).first()
            if record:
                record.aisle_name = aisle_name
                record.bay_number = bay_number
                record.sequence_order = sequence_order
                record.source = source
                record.save(update_fields=["aisle_name", "bay_number", "sequence_order", "source", "updated_at"])
                return record
            else:
                return StoreItemAisle.objects.create(
                    store=store,
                    item_name_normalized=item_name_normalized,
                    aisle_name=aisle_name,
                    bay_number=bay_number,
                    sequence_order=sequence_order,
                    source=source,
                )
        except Exception as error:
            if "locked" in str(error).lower() and attempt < 3:
                time.sleep(0.1 * (2 ** attempt))
                continue
            logger.warning(f"Failed to persist StoreItemAisle for {item_name_normalized}: {error}")
            return None
    return None


def resolve_store_aisle(
    store: StoreLocation,
    item_name: str,
    category: str | None = None,
) -> dict[str, Any] | None:
    """
    Resolve and cache the physical store aisle for a grocery item from the store chain API.

    Resolution strategy:
    1. Check the local StoreItemAisle database cache for existing API or manual entries.
    2. If missing and store is a Kroger location with API enabled, query live Kroger API and cache result.
    3. If it cannot be determined from the store chain API, return None (leave blank).

    Args:
        store: Target StoreLocation instance.
        item_name: The name of the grocery item.
        category: Optional category string (retained for backward compatibility; ignored for pseudo-aisles).

    Returns:
        Dict with aisle_name, bay_number, sequence_order, and source ('api', 'manual') or None.
    """
    clean_name = inflection.singularize(item_name.strip().lower())

    # 1. Check local database cache for api or manual mapping
    cached = StoreItemAisle.objects.filter(
        store=store,
        item_name_normalized=clean_name,
        source__in=["api", "manual"],
    ).first()
    if cached:
        if cached.aisle_name:
            return {
                "aisle_name": cached.aisle_name,
                "bay_number": cached.bay_number,
                "sequence_order": cached.sequence_order,
                "source": cached.source,
            }
        return None

    # 2. Query Kroger API if applicable
    if store.chain == "kroger" and store.external_store_id and kroger_client.is_configured:
        api_result = kroger_client.lookup_product_aisle(store.external_store_id, clean_name)
        if api_result and api_result.get("aisle_name"):
            aisle_record = _save_store_item_aisle(
                store=store,
                item_name_normalized=clean_name,
                aisle_name=api_result["aisle_name"],
                bay_number=api_result.get("bay_number", ""),
                sequence_order=api_result.get("sequence_order", 100),
                source="api",
            )
            if aisle_record:
                return {
                    "aisle_name": aisle_record.aisle_name,
                    "bay_number": aisle_record.bay_number,
                    "sequence_order": aisle_record.sequence_order,
                    "source": "api",
                }
            return {
                "aisle_name": api_result["aisle_name"],
                "bay_number": api_result.get("bay_number", ""),
                "sequence_order": api_result.get("sequence_order", 100),
                "source": "api",
            }
        else:
            # Negative cache: record that API returned no aisle location so we don't spam API
            _save_store_item_aisle(
                store=store,
                item_name_normalized=clean_name,
                aisle_name="",
                bay_number="",
                sequence_order=999,
                source="api",
            )

    # 3. Cannot be determined from store chain API -> leave blank
    return None


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
