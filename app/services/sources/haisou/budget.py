from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_SEARCH_CALLS = 0
_VALIDATE_CALLS = 0
_WINDOW_STARTED = 0.0

# Rolling window budget for paid API calls.
WINDOW_SECONDS = 3600.0
MAX_SEARCH_PER_WINDOW = 40
MAX_VALIDATE_PER_WINDOW = 60

_SEARCH_CACHE: dict[str, tuple[float, Any]] = {}
_VALIDATE_CACHE: dict[str, tuple[float, Any]] = {}
SEARCH_CACHE_TTL_SECONDS = 900.0
VALIDATE_CACHE_TTL_SECONDS = 600.0
_CACHE_MAX = 256


def reset_haisou_budget_for_tests() -> None:
    global _SEARCH_CALLS, _VALIDATE_CALLS, _WINDOW_STARTED
    with _LOCK:
        _SEARCH_CALLS = 0
        _VALIDATE_CALLS = 0
        _WINDOW_STARTED = 0.0
        _SEARCH_CACHE.clear()
        _VALIDATE_CACHE.clear()


def haisou_budget_snapshot() -> dict[str, int | float]:
    _roll_window()
    with _LOCK:
        return {
            "search_calls": int(_SEARCH_CALLS),
            "validate_calls": int(_VALIDATE_CALLS),
            "max_search": MAX_SEARCH_PER_WINDOW,
            "max_validate": MAX_VALIDATE_PER_WINDOW,
            "search_cache": len(_SEARCH_CACHE),
            "validate_cache": len(_VALIDATE_CACHE),
        }


def allow_haisou_search() -> bool:
    _roll_window()
    with _LOCK:
        return _SEARCH_CALLS < MAX_SEARCH_PER_WINDOW


def allow_haisou_validate() -> bool:
    _roll_window()
    with _LOCK:
        return _VALIDATE_CALLS < MAX_VALIDATE_PER_WINDOW


def note_haisou_search() -> None:
    global _SEARCH_CALLS
    _roll_window()
    with _LOCK:
        _SEARCH_CALLS += 1


def note_haisou_validate() -> None:
    global _VALIDATE_CALLS
    _roll_window()
    with _LOCK:
        _VALIDATE_CALLS += 1


def get_cached_haisou_search(key: str) -> Any | None:
    return _cache_get(_SEARCH_CACHE, key, SEARCH_CACHE_TTL_SECONDS)


def set_cached_haisou_search(key: str, value: Any) -> None:
    _cache_set(_SEARCH_CACHE, key, value)


def get_cached_haisou_validate(key: str) -> Any | None:
    return _cache_get(_VALIDATE_CACHE, key, VALIDATE_CACHE_TTL_SECONDS)


def set_cached_haisou_validate(key: str, value: Any) -> None:
    _cache_set(_VALIDATE_CACHE, key, value)


def search_cache_key(query: str, *, platforms: list[str] | None, page_size: int, search_in: str) -> str:
    plats = ",".join(sorted(str(item).strip().lower() for item in (platforms or []) if str(item).strip()))
    return f"{str(query or '').strip().casefold()}|{plats}|{int(page_size)}|{str(search_in or 'title').strip().lower()}"


def validate_cache_key(url: str, pwd: str | None) -> str:
    return f"{str(url or '').strip()}|{str(pwd or '').strip()}"


def _roll_window() -> None:
    global _SEARCH_CALLS, _VALIDATE_CALLS, _WINDOW_STARTED
    now = time.monotonic()
    with _LOCK:
        if not _WINDOW_STARTED or (now - _WINDOW_STARTED) >= WINDOW_SECONDS:
            _WINDOW_STARTED = now
            _SEARCH_CALLS = 0
            _VALIDATE_CALLS = 0


def _cache_get(store: dict[str, tuple[float, Any]], key: str, ttl: float) -> Any | None:
    now = time.monotonic()
    with _LOCK:
        item = store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            store.pop(key, None)
            return None
        return value


def _cache_set(store: dict[str, tuple[float, Any]], key: str, value: Any) -> None:
    now = time.monotonic()
    with _LOCK:
        if len(store) >= _CACHE_MAX:
            # Drop oldest-ish entries cheaply.
            for stale_key, (expires_at, _) in list(store.items())[: max(1, _CACHE_MAX // 8)]:
                if expires_at <= now:
                    store.pop(stale_key, None)
            if len(store) >= _CACHE_MAX:
                for stale_key in list(store.keys())[: max(1, _CACHE_MAX // 8)]:
                    store.pop(stale_key, None)
        store[key] = (now + 1.0, value)  # placeholder overwritten below
        # Fix TTL after size control.
        ttl = SEARCH_CACHE_TTL_SECONDS if store is _SEARCH_CACHE else VALIDATE_CACHE_TTL_SECONDS
        store[key] = (now + ttl, value)
