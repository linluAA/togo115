from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Small process-local TTL cache with max size and hit/miss counters."""

    def __init__(self, *, max_size: int, ttl_seconds: float) -> None:
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._items: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                self.misses += 1
                return None
            if entry.expires_at <= now:
                self._items.pop(key, None)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return entry.value

    def set(self, key: str, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            self._items[key] = _CacheEntry(value=value, expires_at=now + self.ttl_seconds)
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self.hits, "misses": self.misses, "size": len(self._items)}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = 0
            self.misses = 0


# Message-level extract result cache: avoids redoing neighbor/button/page work.
TELEGRAM_MESSAGE_EXTRACT_CACHE = TTLCache(max_size=512, ttl_seconds=900)

# External resource page parse cache: stores extracted 115 links for a page URL.
TELEGRAM_EXTERNAL_PAGE_CACHE = TTLCache(max_size=256, ttl_seconds=1800)


def message_extract_cache_key(source: str, message_id: Any) -> str:
    return f"{source}:{message_id}"


def get_cached_message_extract(source: str, message_id: Any) -> list[Any] | None:
    if not message_id:
        return None
    cached = TELEGRAM_MESSAGE_EXTRACT_CACHE.get(message_extract_cache_key(source, message_id))
    if cached is None:
        return None
    # Return shallow copies so callers can mutate safely.
    return list(cached)


def set_cached_message_extract(source: str, message_id: Any, results: list[Any]) -> None:
    if not message_id:
        return
    TELEGRAM_MESSAGE_EXTRACT_CACHE.set(message_extract_cache_key(source, message_id), list(results))


def get_cached_external_page_links(page_url: str) -> list[str] | None:
    cached = TELEGRAM_EXTERNAL_PAGE_CACHE.get(str(page_url or ""))
    if cached is None:
        return None
    return list(cached)


def set_cached_external_page_links(page_url: str, links: list[str]) -> None:
    url = str(page_url or "")
    if not url:
        return
    TELEGRAM_EXTERNAL_PAGE_CACHE.set(url, list(links))


def extract_cache_stats() -> dict[str, dict[str, int]]:
    return {
        "message_extract": TELEGRAM_MESSAGE_EXTRACT_CACHE.stats(),
        "external_page": TELEGRAM_EXTERNAL_PAGE_CACHE.stats(),
    }


def clear_extract_caches() -> None:
    TELEGRAM_MESSAGE_EXTRACT_CACHE.clear()
    TELEGRAM_EXTERNAL_PAGE_CACHE.clear()
