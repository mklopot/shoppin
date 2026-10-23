"""
Background scheduler service for automated preset list recurrences.

Runs an in-process daemon thread to continuously check and execute due preset schedules,
broadcasting real-time notifications and list updates across all open tabs.
"""

import logging
import threading
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()
_execution_lock = threading.Lock()


def process_due_schedules(force: bool = False) -> list[dict[str, Any]]:
    """
    Check and execute all due preset list schedules across all workspaces.

    Thread-safe and guarded against overlapping concurrent executions.

    Args:
        force: If True, execute all enabled preset schedules regardless of due date.

    Returns:
        List of execution result dicts for presets that were processed.
    """
    if not _execution_lock.acquire(blocking=False):
        logger.debug("Scheduler execution already in progress, skipping duplicate cycle.")
        return []

    from apps.shopping.models import ShoppingList
    from apps.shopping.services.preset_service import apply_preset_scheduled_refresh

    close_old_connections()
    results: list[dict[str, Any]] = []
    try:
        now = timezone.now()
        qs = ShoppingList.objects.filter(is_preset=True, is_schedule_enabled=True)
        if not force:
            qs = qs.filter(next_occurrence__isnull=False, next_occurrence__lte=now)

        due_presets = list(qs.select_related("workspace"))
        for preset in due_presets:
            try:
                logger.info(
                    "Scheduler executing refresh for preset '%s' (workspace: %s, next was: %s)",
                    preset.name,
                    getattr(preset.workspace, "name", "None"),
                    preset.next_occurrence,
                )
                res = apply_preset_scheduled_refresh(preset)
                results.append(res)
            except Exception as err:
                logger.exception("Failed to execute scheduled refresh for preset '%s': %s", preset.name, err)
    except Exception as exc:
        logger.exception("Error checking due preset schedules: %s", exc)
    finally:
        close_old_connections()
        _execution_lock.release()

    return results


def _preset_scheduler_loop(poll_interval: int = 5) -> None:
    """Daemon thread loop checking for due schedules at regular intervals."""
    logger.info("Preset background scheduler loop started (poll interval: %ds)", poll_interval)
    while not _stop_event.is_set():
        try:
            process_due_schedules()
        except Exception as err:
            logger.exception("Unhandled error in preset scheduler loop: %s", err)

        if _stop_event.wait(timeout=poll_interval):
            break

    logger.info("Preset background scheduler loop stopped.")


def start_preset_scheduler(poll_interval: int = 5) -> None:
    """
    Start the background preset scheduler daemon thread if not already running.
    """
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_preset_scheduler_loop,
        args=(poll_interval,),
        name="PresetSchedulerThread",
        daemon=True,
    )
    _scheduler_thread.start()
    logger.info("Started background preset scheduler thread (daemon).")


def stop_preset_scheduler() -> None:
    """Signal the background preset scheduler thread to stop."""
    global _scheduler_thread
    _stop_event.set()
    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=2)
    _scheduler_thread = None
