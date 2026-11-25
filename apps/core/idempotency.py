"""
HTTP Post Idempotency Protection Middleware.

Guards against duplicate mutations caused by flaky mobile retries or offline
queue replays using client-generated ``X-Idempotency-Key`` headers scoped strictly
to the authenticated user (or anonymous session), workspace, and request path.
"""

import hashlib
from typing import Any, Callable

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

IDEMPOTENCY_TTL_SECONDS = 60
MAX_KEY_LENGTH = 128


class IdempotencyMiddleware:
    """
    Cache and replay successful mutating POST responses keyed by ``X-Idempotency-Key``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_key = request.headers.get("X-Idempotency-Key", "").strip()
        if request.method != "POST" or not raw_key or len(raw_key) > MAX_KEY_LENGTH:
            return self.get_response(request)

        cache_key = self._build_cache_key(request, raw_key)
        cached_payload: dict[str, Any] | None = cache.get(cache_key)
        if cached_payload is not None:
            replayed = HttpResponse(
                content=cached_payload["content"],
                status=cached_payload["status"],
                content_type=cached_payload["content_type"],
            )
            for hdr_name, hdr_val in cached_payload.get("headers", {}).items():
                replayed[hdr_name] = hdr_val
            replayed["X-Idempotent-Replay"] = "1"
            return replayed

        response = self.get_response(request)

        if 200 <= response.status_code < 400 and not getattr(response, "streaming", False):
            preserved_headers = {
                key: val
                for key, val in response.items()
                if key.lower().startswith(("x-", "hx-"))
            }
            cache.set(
                cache_key,
                {
                    "status": response.status_code,
                    "content": response.content,
                    "content_type": response.get("Content-Type", "text/html; charset=utf-8"),
                    "headers": preserved_headers,
                },
                timeout=IDEMPOTENCY_TTL_SECONDS,
            )

        return response

    @staticmethod
    def _build_cache_key(request: HttpRequest, raw_key: str) -> str:
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            actor_scope = f"u:{user.pk}"
        else:
            session = getattr(request, "session", None)
            session_key = getattr(session, "session_key", None) or "anon"
            actor_scope = f"s:{session_key}"

        session = getattr(request, "session", None)
        workspace_id = session.get("active_workspace_id", "") if session else ""
        digest = hashlib.sha256(
            f"{actor_scope}|{workspace_id}|{request.path}|{raw_key}".encode("utf-8")
        ).hexdigest()
        return f"shoppin_idemp:{digest}"


def mark_purge_client_caches(response: HttpResponse) -> HttpResponse:
    """Signal the browser shell and service worker to purge user/workspace caches."""
    response.set_cookie("shoppin_purge_cache", "1", max_age=30, samesite="Lax")
    return response
