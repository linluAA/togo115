from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from typing import Any

from app.services.integration_state import get_flow, save_flow
from app.services.sources.rss_torznab import SearchResult
from app.services.magnet.constants import (
    TG_BOT_MAGNET_CACHE_MAX_ITEMS,
    TG_BOT_MAGNET_CACHE_TTL_SECONDS,
    _MAGNET_SEARCH_CACHE_FLOW,
    _magnet_search_cache,
)


def _cached_magnet_search(media_type: str, tmdb_id: int, limit: int) -> tuple[dict[str, Any], list[SearchResult]] | None:
    _load_magnet_search_cache()
    _prune_magnet_search_cache()
    item = _magnet_search_cache.get(_magnet_cache_key(media_type, tmdb_id, limit))
    if not item:
        return None
    detail = dict(item.get("detail") or {})
    results = [result for result in item.get("results") or [] if isinstance(result, SearchResult)]
    return detail, results

def _store_magnet_search_cache(media_type: str, tmdb_id: int, limit: int, detail: dict[str, Any], results: list[SearchResult]) -> None:
    _load_magnet_search_cache()
    _magnet_search_cache[_magnet_cache_key(media_type, tmdb_id, limit)] = {
        "created_at": time.time(),
        "detail": dict(detail),
        "results": list(results),
    }
    _prune_magnet_search_cache()
    _save_magnet_search_cache()

def _prune_magnet_search_cache() -> None:
    _load_magnet_search_cache()
    now = time.time()
    expired = [
        key
        for key, item in _magnet_search_cache.items()
        if now - float(item.get("created_at") or 0) > TG_BOT_MAGNET_CACHE_TTL_SECONDS
    ]
    for key in expired:
        _magnet_search_cache.pop(key, None)
    overflow = len(_magnet_search_cache) - TG_BOT_MAGNET_CACHE_MAX_ITEMS
    if overflow > 0:
        oldest = sorted(_magnet_search_cache.items(), key=lambda item: float(item[1].get("created_at") or 0))[:overflow]
        for key, _ in oldest:
            _magnet_search_cache.pop(key, None)

def _load_magnet_search_cache() -> None:
    if _magnet_search_cache:
        return
    try:
        payload = get_flow(_MAGNET_SEARCH_CACHE_FLOW)
    except Exception:
        return
    raw_items = payload.get("items") or {}
    if not isinstance(raw_items, dict):
        return
    for key, item in raw_items.items():
        if not isinstance(item, dict):
            continue
        _magnet_search_cache[str(key)] = {
            "created_at": item.get("created_at") or 0,
            "detail": item.get("detail") or {},
            "results": _deserialize_search_results(item.get("results") or []),
        }

def _save_magnet_search_cache() -> None:
    items: dict[str, Any] = {}
    for key, item in _magnet_search_cache.items():
        items[key] = {
            "created_at": item.get("created_at") or time.time(),
            "detail": item.get("detail") or {},
            "results": [_serialize_search_result(result) for result in item.get("results") or []],
        }
    try:
        save_flow(_MAGNET_SEARCH_CACHE_FLOW, {"items": items})
    except Exception:
        pass

def _magnet_cache_key(media_type: str, tmdb_id: int, limit: int) -> str:
    return f"{str(media_type or '').strip()}:{int(tmdb_id or 0)}:{int(limit or TG_BOT_MAGNET_LIMIT)}"

def _serialize_search_result(result: SearchResult) -> dict[str, Any]:
    return asdict(result) if is_dataclass(result) else dict(result)

def _deserialize_search_results(items: list[Any]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or item.get("link") or ""),
                source=str(item.get("source") or "tg_bot"),
                message_id=item.get("message_id"),
                context=str(item.get("context") or ""),
                priority=int(item.get("priority") or 0),
            )
        )
    return results
