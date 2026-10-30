"""
Shopping services package for external integrations, aisle resolution, and list organization logic.
"""

from apps.shopping.services.broadcaster import broadcast_shopping_list_update
from apps.shopping.services.cleanup_service import (
    purge_all_expired_completed_items,
    purge_expired_completed_items,
)
from apps.shopping.services.list_organizer import ShoppingListOrganizer
from apps.shopping.services.scheduler import (
    process_due_schedules,
    start_preset_scheduler,
    stop_preset_scheduler,
)
from apps.shopping.services.store_service import (
    KrogerAPIClient,
    get_aisle_sort_key,
    get_ingredient_search_candidates,
    get_known_aisles,
    get_known_categories,
    get_nearest_stores,
    haversine_distance,
    resolve_store_aisle,
    warm_store_aisles_async,
)

__all__ = [
    "broadcast_shopping_list_update",
    "purge_expired_completed_items",
    "purge_all_expired_completed_items",
    "ShoppingListOrganizer",
    "process_due_schedules",
    "start_preset_scheduler",
    "stop_preset_scheduler",
    "KrogerAPIClient",
    "get_aisle_sort_key",
    "get_ingredient_search_candidates",
    "get_known_aisles",
    "get_known_categories",
    "get_nearest_stores",
    "haversine_distance",
    "resolve_store_aisle",
    "warm_store_aisles_async",
]
