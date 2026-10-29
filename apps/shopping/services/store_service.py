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
from django.db.models import Q

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

# Modifiers and culinary prefixes/suffixes to strip when generating candidate search terms
COMMON_PREP_MODIFIERS: set[str] = {
    "freshly ground", "freshly", "fresh", "ground", "diced", "minced", "chopped",
    "crushed", "sliced", "grated", "shredded", "peeled", "cooked", "roasted",
    "toasted", "dried", "dry", "frozen", "raw", "organic", "boneless skinless",
    "boneless", "skinless", "wild", "lean", "extra-virgin", "extra virgin", "pure",
    "whole", "powder", "seeds", "seed", "flakes", "flake", "leaves", "leaf", "leafe",
    "halves", "half", "pieces", "piece", "cubes", "cube", "cloves of", "clove of",
    "cloves", "clove", "stalks of", "stalk of", "stalks", "stalk", "sprigs of",
    "sprig of", "sprigs", "sprig", "leaves of", "leaf of", "heads of", "head of",
    "heads", "head", "bunches of", "bunch of", "bunches", "bunch", "cans of", "can of",
    "cans", "can", "packages of", "package of", "packs of", "pack of", "packages",
    "package", "packs", "pack", "of", "and", "or", "with",
}

PREP_STOP_WORDS: set[str] = {
    "powder", "cloves", "clove", "stalks", "stalk", "sprigs", "sprig", "leaves",
    "leaf", "leafe", "heads", "head", "bunches", "bunch", "cans", "can", "packs",
    "pack", "packages", "package", "pieces", "piece", "cubes", "cube", "halves",
    "half", "seeds", "seed", "flakes", "flake", "of", "and", "or", "with", "fresh",
    "ground", "diced", "minced", "chopped", "sliced", "raw", "frozen", "dried", "dry",
}

BARE_ADJECTIVES: set[str] = {
    "black", "white", "yellow", "red", "green", "olive", "extra", "virgin",
    "hot", "sweet", "sour", "mild", "spicy", "dark", "light", "large", "small", "medium",
}

# Standard department names that are consistent across Kroger/King Soopers locations
UNIVERSAL_DEPARTMENTS: set[str] = {
    "produce", "meat", "seafood", "deli", "bakery", "dairy", "eggs and dairy", "frozen",
}

# In-memory negative lookup cache: (store_id, candidate_term) -> timestamp (TTL: 1 hour)
_NEGATIVE_LOOKUP_CACHE: dict[tuple[int, str], float] = {}
_NEGATIVE_CACHE_TTL_SECONDS = 3600.0


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
        with urllib.request.urlopen(req, timeout=3.5) as resp:  # nosec: B310
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

                clean_street = (
                    street.replace("South ", "S ")
                    .replace("North ", "N ")
                    .replace("East ", "E ")
                    .replace("West ", "W ")
                    .replace("Street", "St")
                    .replace("Avenue", "Ave")
                    .replace("Boulevard", "Blvd")
                    .replace("Drive", "Dr")
                    .replace("Road", "Rd")
                    .replace("Parkway", "Pkwy")
                )
                if clean_street and not any(sep in raw_name for sep in ["#", "(", " - ", "@", "/"]):
                    distinct_name = f"{raw_name} ({clean_street})"
                else:
                    distinct_name = raw_name

                store_obj, _ = StoreLocation.objects.get_or_create(
                    name=distinct_name,
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
        discovery = search_and_discover_stores(latitude=latitude, longitude=longitude, limit=limit, discover_remote=True)
        return discovery["stores"]

    return store_results[:limit]


class KrogerAPIClient:
    """
    Client for the official Kroger Developer API.

    Handles OAuth2 Client Credentials token negotiation and product aisle lookups.
    Reference: https://developer.kroger.com/reference/
    """
    TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
    PRODUCTS_URL = "https://api.kroger.com/v1/products"
    LOCATIONS_URL = "https://api.kroger.com/v1/locations"

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
            with urllib.request.urlopen(request, timeout=10) as response:  # nosec: B310
                response_data = json.loads(response.read().decode())
                self._cached_token = response_data.get("access_token")
                return self._cached_token
        except Exception as error:
            logger.warning(f"Failed to fetch Kroger access token: {error}")
            return None

    def find_locations(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        zip_code: str | None = None,
        term: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Query Kroger API /v1/locations to discover physical Kroger/King Soopers stores.

        Supports querying by lat/long, zip code, or search term.
        """
        token = self.get_access_token()
        if not token:
            return []

        params: dict[str, Any] = {"filter.limit": limit}
        if latitude is not None and longitude is not None:
            params["filter.latLong.near"] = f"{latitude},{longitude}"
        elif zip_code:
            params["filter.zipCode.near"] = zip_code.strip()
        elif term:
            params["filter.term"] = term.strip()

        query_str = urllib.parse.urlencode(params)
        url = f"{self.LOCATIONS_URL}?{query_str}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # nosec: B310
                data = json.loads(response.read().decode())
                return data.get("data", [])
        except Exception as error:
            logger.warning(f"Kroger locations lookup failed for params {params}: {error}")
            return []

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
            "filter.limit": 5,
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
            with urllib.request.urlopen(request, timeout=12) as response:  # nosec: B310
                data = json.loads(response.read().decode())
                products = data.get("data", [])
                if not products:
                    return None

                for product in products:
                    aisle_locations = product.get("aisleLocations", [])
                    if not aisle_locations:
                        continue

                    first_location = aisle_locations[0]
                    desc = (first_location.get("description") or "").strip()
                    num = (first_location.get("number") or "").strip()
                    aisle_name = desc or (f"Aisle {num}" if num else "")
                    if not aisle_name:
                        continue

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
                return None
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
    Guarantees that empty aisle records are never persisted to the database.
    """
    clean_aisle = (aisle_name or "").strip()
    if not clean_aisle:
        return None

    import time
    for attempt in range(4):
        try:
            record = StoreItemAisle.objects.filter(
                store=store,
                item_name_normalized=item_name_normalized,
            ).first()
            if record:
                record.aisle_name = clean_aisle
                record.bay_number = bay_number
                record.sequence_order = sequence_order
                record.source = source
                record.save(update_fields=["aisle_name", "bay_number", "sequence_order", "source", "last_updated"])
                return record
            else:
                return StoreItemAisle.objects.create(
                    store=store,
                    item_name_normalized=item_name_normalized,
                    aisle_name=clean_aisle,
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


def normalize_search_term(raw_name: str) -> str:
    """
    Format item names for product search.
    Converts inverted catalog styles like 'apples, green' to 'green apples'
    and 'beans, fresh' to 'fresh beans'.
    """
    clean = raw_name.strip().lower()
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) == 2:
            clean = f"{parts[1]} {parts[0]}"
        elif len(parts) > 2:
            clean = " ".join(reversed(parts))
    return inflection.singularize(clean)


def get_ingredient_search_candidates(raw_name: str) -> list[str]:
    """
    Generate prioritized search candidate terms for an ingredient name by stripping
    culinary descriptors, preparation techniques, parenthetical notes, and quantities.

    Examples:
        'freshly ground black pepper' -> ['freshly ground black pepper', 'black pepper', 'pepper']
        'cloves garlic, minced'       -> ['cloves garlic', 'garlic']
        'diced yellow onion'          -> ['diced yellow onion', 'yellow onion', 'onion']
        'fresh cilantro leafe'        -> ['fresh cilantro leafe', 'cilantro']
        'coriander powder'            -> ['coriander powder', 'coriander', 'ground coriander']
        'apples, green'               -> ['green apples', 'green apple', 'apples', 'apple']
    """
    candidates: list[str] = []

    def _add(cand: str) -> None:
        cand = cand.strip().lower()
        cand = re.sub(r"\s+", " ", cand)
        if (
            cand
            and cand not in candidates
            and len(cand) >= 2
            and cand not in PREP_STOP_WORDS
            and cand not in BARE_ADJECTIVES
        ):
            candidates.append(cand)
        try:
            sing = inflection.singularize(cand)
            if (
                sing
                and sing not in candidates
                and len(sing) >= 2
                and sing not in PREP_STOP_WORDS
                and sing not in BARE_ADJECTIVES
            ):
                candidates.append(sing)
        except Exception:
            pass

    raw_clean = raw_name.strip().lower()
    _add(raw_clean)

    clean = raw_clean
    clean = re.sub(r"\(.*?\)", "", clean).strip()

    # Comma-separated prep: 'garlic, minced' or catalog style 'apples, green'
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        if len(parts) >= 2:
            second_part = parts[1]
            if any(p in second_part for p in ["mince", "dice", "chop", "slice", "drain", "thaw", "divide", "taste", "fresh"]):
                clean = parts[0]
            else:
                clean = f"{parts[1]} {parts[0]}"

    # Strip leading quantities or fractions: e.g. '1/2', '2', '3.5', '1-2'
    clean = re.sub(r"^[\d/\.\s\-]+\s*", "", clean).strip()
    _add(clean)

    # Iteratively strip leading/trailing modifiers
    current = clean
    changed = True
    while changed:
        changed = False
        words = current.split()
        if not words:
            break
        # Check prefix matches of length 3, 2, 1
        for length in (3, 2, 1):
            if len(words) >= length:
                prefix = " ".join(words[:length])
                if prefix in COMMON_PREP_MODIFIERS:
                    current = " ".join(words[length:])
                    _add(current)
                    changed = True
                    break
        if changed:
            continue
        # Check suffix matches of length 2, 1
        for length in (2, 1):
            if len(words) >= length:
                suffix = " ".join(words[-length:])
                if suffix in COMMON_PREP_MODIFIERS:
                    current = " ".join(words[:-length])
                    _add(current)
                    changed = True
                    break

    # Culinary special-case expansions
    if "coriander" in clean:
        _add("ground coriander")
        _add("coriander")
    if "black pepper" in clean:
        _add("black pepper")
        _add("pepper")
    if "garlic" in clean:
        _add("garlic")
    if "onion" in clean:
        if "yellow" in clean:
            _add("yellow onion")
        elif "white" in clean:
            _add("white onion")
        elif "red" in clean:
            _add("red onion")
        elif "green" in clean:
            _add("green onion")
        _add("onion")

    # Decompose multi-word remaining tokens into nouns
    words = [w for w in current.split() if w not in PREP_STOP_WORDS and w not in BARE_ADJECTIVES]
    if len(words) >= 2:
        _add(words[0])
        _add(words[-1])

    return candidates


def resolve_store_aisle(
    store: StoreLocation,
    item_name: str,
    category: str | None = None,
) -> dict[str, Any] | None:
    """
    Resolve and cache the physical store aisle for a grocery item from the store chain API.

    Resolution strategy:
    1. Check local StoreItemAisle cache for existing API or manual entries matching candidate terms.
    2. If missing and store is a Kroger location with API enabled, query Kroger API across candidates.
    3. If store-specific API has no match, check for universal perimeter departments from other Kroger stores.
    4. If it cannot be determined, return None (leave blank). Does NOT persist empty negative records.

    Args:
        store: Target StoreLocation instance.
        item_name: The name of the grocery item.
        category: Optional category string (retained for backward compatibility; ignored for pseudo-aisles).

    Returns:
        Dict with aisle_name, bay_number, sequence_order, and source ('api', 'manual') or None.
    """
    import time
    clean_original = inflection.singularize(item_name.strip().lower())
    candidates = get_ingredient_search_candidates(item_name)
    if clean_original not in candidates:
        candidates.insert(0, clean_original)

    # 1. Check local database cache for api or manual mapping
    cached = (
        StoreItemAisle.objects.filter(
            store=store,
            item_name_normalized__in=candidates,
            source__in=["api", "manual"],
        )
        .exclude(aisle_name="")
        .order_by("-source", "-last_updated")
        .first()
    )
    if cached and cached.aisle_name:
        # If original item name isn't stored yet, record the alias mapping
        if cached.item_name_normalized != clean_original:
            _save_store_item_aisle(
                store=store,
                item_name_normalized=clean_original,
                aisle_name=cached.aisle_name,
                bay_number=cached.bay_number,
                sequence_order=cached.sequence_order,
                source=cached.source,
            )
        return {
            "aisle_name": cached.aisle_name,
            "bay_number": cached.bay_number,
            "sequence_order": cached.sequence_order,
            "source": cached.source,
        }

    # 2. Query Kroger API across candidates if applicable
    now = time.time()
    if store.chain == "kroger" and store.external_store_id and kroger_client.is_configured:
        for candidate in candidates:
            # Check in-memory negative cache to prevent spamming
            cache_key = (store.id, candidate)
            cached_time = _NEGATIVE_LOOKUP_CACHE.get(cache_key)
            if cached_time and (now - cached_time < _NEGATIVE_CACHE_TTL_SECONDS):
                continue

            api_result = kroger_client.lookup_product_aisle(store.external_store_id, candidate)
            if api_result and api_result.get("aisle_name"):
                # Persist for original requested name AND matched candidate
                _save_store_item_aisle(
                    store=store,
                    item_name_normalized=clean_original,
                    aisle_name=api_result["aisle_name"],
                    bay_number=api_result.get("bay_number", ""),
                    sequence_order=api_result.get("sequence_order", 100),
                    source="api",
                )
                if candidate != clean_original:
                    _save_store_item_aisle(
                        store=store,
                        item_name_normalized=candidate,
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
            else:
                # Add candidate to in-memory negative cache (never store empty DB records)
                _NEGATIVE_LOOKUP_CACHE[cache_key] = now

    # 3. Fallback: Universal perimeter department from other Kroger stores
    if store.chain == "kroger":
        other_kroger_match = (
            StoreItemAisle.objects.filter(
                store__chain="kroger",
                item_name_normalized__in=candidates,
            )
            .exclude(aisle_name="")
            .order_by("-last_updated")
            .first()
        )
        if other_kroger_match and other_kroger_match.aisle_name:
            matched_aisle_lower = other_kroger_match.aisle_name.strip().lower()
            if any(dept in matched_aisle_lower for dept in UNIVERSAL_DEPARTMENTS):
                dept_name = other_kroger_match.aisle_name.strip()
                _save_store_item_aisle(
                    store=store,
                    item_name_normalized=clean_original,
                    aisle_name=dept_name,
                    bay_number="",
                    sequence_order=other_kroger_match.sequence_order,
                    source="api",
                )
                return {
                    "aisle_name": dept_name,
                    "bay_number": "",
                    "sequence_order": other_kroger_match.sequence_order,
                    "source": "api",
                }

    # 4. Cannot be determined from store chain API -> leave blank (never write empty DB records)
    return None


def ingest_kroger_location(loc_data: dict[str, Any]) -> StoreLocation | None:
    """
    Ingest or update a StoreLocation record from Kroger locations API response.
    """
    loc_id = loc_data.get("locationId")
    if not loc_id:
        return None
    raw_name = loc_data.get("name", "")
    addr = loc_data.get("address", {})
    geo = loc_data.get("geolocation", {})
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    if lat is None or lon is None:
        return None

    clean_subname = (
        raw_name.replace("King Soopers - ", "")
        .replace("Kroger - ", "")
        .replace("King Soopers", "")
        .strip(" -")
    )
    street = addr.get("addressLine1", "").strip()
    if clean_subname:
        display_name = f"King Soopers #{loc_id} ({clean_subname})"
    elif street:
        display_name = f"King Soopers #{loc_id} ({street})"
    else:
        display_name = f"King Soopers #{loc_id}"

    store, created = StoreLocation.objects.get_or_create(
        external_store_id=loc_id,
        defaults={
            "name": display_name,
            "chain": "kroger",
            "address": street,
            "city": addr.get("city", "").strip(),
            "state": addr.get("state", "CO").strip(),
            "zip_code": addr.get("zipCode", "").strip(),
            "latitude": float(lat),
            "longitude": float(lon),
        },
    )
    if not created:
        updated = False
        if not store.latitude:
            store.latitude = float(lat)
            updated = True
        if not store.longitude:
            store.longitude = float(lon)
            updated = True
        if not store.address and street:
            store.address = street
            updated = True
        if updated:
            store.save(update_fields=["latitude", "longitude", "address"])
    return store


def geocode_address_or_city(query: str) -> tuple[float, float, str] | None:
    """
    Resolve an address, city, neighborhood, or ZIP code to (latitude, longitude, display_name)
    using OpenStreetMap Nominatim.
    """
    clean_query = query.strip()
    if not clean_query:
        return None
    try:
        url = (
            f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(clean_query)}"
            f"&format=json&limit=1&addressdetails=1"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ShoppinApp-StoreLocator/2.0"},
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:  # nosec: B310
            data = json.loads(resp.read().decode())
            if data and len(data) > 0:
                return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", "")
    except Exception as error:
        logger.warning(f"Geocoding failed for '{query}': {error}")
    return None


def search_and_discover_stores(
    query: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    limit: int = 15,
    discover_remote: bool = True,
) -> dict[str, Any]:
    """
    Search and dynamically discover physical supermarket locations by text query
    (city, ZIP, address, or store name) or coordinates (GPS, interactive map pin).
    """
    clean_query = (query or "").strip()
    target_lat = latitude
    target_lon = longitude
    resolved_name = ""

    # 1. Handle text search query
    if clean_query and discover_remote:
        if clean_query.isdigit() and len(clean_query) == 5:
            if kroger_client.is_configured:
                kroger_stores = kroger_client.find_locations(zip_code=clean_query, limit=10)
                for ks in kroger_stores:
                    ingest_kroger_location(ks)
            geo_res = geocode_address_or_city(f"{clean_query}, USA")
            if geo_res:
                target_lat, target_lon, resolved_name = geo_res
        else:
            geo_res = geocode_address_or_city(clean_query)
            if geo_res:
                target_lat, target_lon, resolved_name = geo_res
                if kroger_client.is_configured:
                    kroger_stores = kroger_client.find_locations(latitude=target_lat, longitude=target_lon, limit=10)
                    for ks in kroger_stores:
                        ingest_kroger_location(ks)
            else:
                if kroger_client.is_configured:
                    kroger_stores = kroger_client.find_locations(term=clean_query, limit=5)
                    for ks in kroger_stores:
                        ingest_kroger_location(ks)

    # 2. If coordinates are provided without query, query Kroger near coordinates
    if target_lat is not None and target_lon is not None and not clean_query and discover_remote:
        if kroger_client.is_configured:
            kroger_stores = kroger_client.find_locations(latitude=target_lat, longitude=target_lon, limit=10)
            for ks in kroger_stores:
                ingest_kroger_location(ks)

    center_lat = target_lat if target_lat is not None else 39.7392
    center_lon = target_lon if target_lon is not None else -104.9903

    # 3. Collect candidates from StoreLocation
    candidates = StoreLocation.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
    if clean_query and not (target_lat and target_lon):
        candidates = candidates.filter(
            Q(name__icontains=clean_query)
            | Q(address__icontains=clean_query)
            | Q(city__icontains=clean_query)
            | Q(zip_code__icontains=clean_query)
            | Q(chain__icontains=clean_query)
        )

    # 4. Calculate distances from center_lat, center_lon
    results = []
    seen_identities: set[str] = set()
    for store in candidates:
        ident = f"{store.chain}:{store.external_store_id or store.address or store.name}"
        if ident in seen_identities:
            continue
        seen_identities.add(ident)

        dist = haversine_distance(center_lat, center_lon, store.latitude, store.longitude)
        results.append({
            "store": store,
            "distance_miles": dist,
        })

    # If all stores are far (>25 mi), discover via OSM
    if not results or (results and results[0]["distance_miles"] > 25.0):
        discovered = discover_nearby_stores_osm(center_lat, center_lon)
        if discovered:
            for st in discovered:
                ident = f"{st.chain}:{st.external_store_id or st.address or st.name}"
                if ident not in seen_identities and st.latitude and st.longitude:
                    seen_identities.add(ident)
                    results.append({
                        "store": st,
                        "distance_miles": haversine_distance(center_lat, center_lon, st.latitude, st.longitude),
                    })

    results.sort(key=lambda r: r["distance_miles"])

    return {
        "stores": results[:limit],
        "center_lat": round(center_lat, 5),
        "center_lon": round(center_lon, 5),
        "resolved_location_name": resolved_name,
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
