from __future__ import annotations

import time

TELEGRAM_INDEX_NEGATIVE_TTL_SECONDS = 120.0
_NEGATIVE_INDEX_CACHE: dict[str, float] = {}


def _negative_cache_key(sources: list[str], queries: list[str]) -> str:
    source_key = ",".join(sorted(str(item) for item in sources))
    query_key = "|".join(str(item) for item in queries)
    return source_key + "::" + query_key


def _negative_cache_hit(sources: list[str], queries: list[str]) -> bool:
    key = _negative_cache_key(sources, queries)
    expires = _NEGATIVE_INDEX_CACHE.get(key)
    if expires is None:
        return False
    if expires <= time.monotonic():
        _NEGATIVE_INDEX_CACHE.pop(key, None)
        return False
    return True


def _negative_cache_store(sources: list[str], queries: list[str]) -> None:
    key = _negative_cache_key(sources, queries)
    _NEGATIVE_INDEX_CACHE[key] = time.monotonic() + TELEGRAM_INDEX_NEGATIVE_TTL_SECONDS
    if len(_NEGATIVE_INDEX_CACHE) > 512:
        now = time.monotonic()
        expired = [item for item, exp in _NEGATIVE_INDEX_CACHE.items() if exp <= now]
        for item in expired:
            _NEGATIVE_INDEX_CACHE.pop(item, None)
        if len(_NEGATIVE_INDEX_CACHE) > 512:
            oldest = sorted(_NEGATIVE_INDEX_CACHE.items(), key=lambda pair: pair[1])[:128]
            for item, _ in oldest:
                _NEGATIVE_INDEX_CACHE.pop(item, None)
