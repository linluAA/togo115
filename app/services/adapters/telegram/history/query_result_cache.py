from __future__ import annotations

import time
from typing import Any

from app.services.types import SearchResult

# Short process-level cache shared across subscription searches in one worker.
POSITIVE_TTL_SECONDS = 180.0
NEGATIVE_TTL_SECONDS = 45.0
MAX_ENTRIES = 512

# key -> (expires_at, results)
_CACHE: dict[str, tuple[float, list[SearchResult]]] = {}


def _key(source: str, query: str) -> str:
    return f"{str(source or '').strip()}\0{str(query or '').strip()}"


def _purge_expired(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    expired = [key for key, (expires_at, _) in _CACHE.items() if expires_at <= current]
    for key in expired:
        _CACHE.pop(key, None)
    if len(_CACHE) <= MAX_ENTRIES:
        return
    # Drop oldest expiries first.
    overflow = sorted(_CACHE.items(), key=lambda item: item[1][0])[: max(0, len(_CACHE) - MAX_ENTRIES)]
    for key, _ in overflow:
        _CACHE.pop(key, None)


def get_cached_query_results(source: str, query: str) -> list[SearchResult] | None:
    key = _key(source, query)
    if not key.strip("\0"):
        return None
    item = _CACHE.get(key)
    if item is None:
        return None
    expires_at, results = item
    if expires_at <= time.monotonic():
        _CACHE.pop(key, None)
        return None
    return list(results)


def set_cached_query_results(source: str, query: str, results: list[Any] | None) -> None:
    key = _key(source, query)
    if not key.strip("\0"):
        return
    payload = list(results or [])
    ttl = POSITIVE_TTL_SECONDS if payload else NEGATIVE_TTL_SECONDS
    _CACHE[key] = (time.monotonic() + ttl, payload)
    _purge_expired()


def clear_query_result_cache() -> None:
    """Test helper."""
    _CACHE.clear()


def query_result_cache_stats() -> dict[str, int]:
    now = time.monotonic()
    positive = 0
    negative = 0
    for expires_at, results in _CACHE.values():
        if expires_at <= now:
            continue
        if results:
            positive += 1
        else:
            negative += 1
    return {"entries": positive + negative, "positive": positive, "negative": negative}
