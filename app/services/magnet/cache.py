from __future__ import annotations

import secrets
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from app.services.integration_state import get_flow, save_flow
from app.services.sources.rss_torznab import SearchResult
from app.services.magnet.constants import (
    TG_BOT_MAGNET_CACHE_MAX_ITEMS,
    TG_BOT_MAGNET_CACHE_TTL_SECONDS,
    TG_BOT_MAGNET_PICK_MAX_ITEMS,
    TG_BOT_MAGNET_PICK_TTL_SECONDS,
    _MAGNET_SEARCH_CACHE_FLOW,
    _PENDING_MAGNET_FLOW,
    _magnet_search_cache,
    _pending_magnet_picks,
)
from app.services.magnet.ranking import _detail_title, _display_source, _resource_size, _result_attr

def pending_magnet_pick(token: str, index: int) -> SearchResult | None:
    _prune_pending_magnet_results()
    item = _pending_magnet_picks.get(token)
    if not item:
        return None
    results = item.get("results") or []
    if index < 0 or index >= len(results):
        return None
    return results[index]


def pending_magnet_choices(token: str, start_index: int = 0) -> list[tuple[int, SearchResult]]:
    _prune_pending_magnet_results()
    item = _pending_magnet_picks.get(token)
    if not item:
        return []
    results = item.get("results") or []
    return [(index, result) for index, result in enumerate(results) if index >= start_index]


def pending_magnet_target_path(token: str) -> str | None:
    _prune_pending_magnet_results()
    item = _pending_magnet_picks.get(token)
    if not item:
        return None
    detail = item.get("detail") or {}
    title = _detail_title(detail) or str(detail.get("title") or detail.get("name") or "").strip()
    if not title:
        return None
    media_type = str(detail.get("media_type") or "").strip()
    root = "电影" if media_type == "movie" else "电视剧"
    return f"/{root}/{title}"


def pending_magnet_detail(token: str) -> dict[str, Any]:
    _prune_pending_magnet_results()
    item = _pending_magnet_picks.get(token)
    if not item:
        return {}
    return dict(item.get("detail") or {})


def pending_magnet_label(token: str, index: int) -> str:
    result = pending_magnet_pick(token, index)
    if not result:
        return "\u78c1\u529b\u8d44\u6e90"
    size = _resource_size(result) or "\u672a\u77e5"
    title = _result_attr(result, "title") or "\u78c1\u529b\u8d44\u6e90"
    return f"{str(title).strip()[:48]} \u00b7 {size}"


def _store_pending_magnet_results(detail: dict[str, Any], results: list[SearchResult]) -> str:
    _load_pending_magnet_results()
    _prune_pending_magnet_results()
    token = secrets.token_urlsafe(6)
    _pending_magnet_picks[token] = {
        "created_at": time.time(),
        "detail": dict(detail),
        "results": list(results),
    }
    _save_pending_magnet_results()
    return token


def _prune_pending_magnet_results() -> None:
    _load_pending_magnet_results()
    now = time.time()
    expired = [
        token
        for token, item in _pending_magnet_picks.items()
        if now - float(item.get("created_at") or 0) > TG_BOT_MAGNET_PICK_TTL_SECONDS
    ]
    for token in expired:
        _pending_magnet_picks.pop(token, None)
    overflow = len(_pending_magnet_picks) - TG_BOT_MAGNET_PICK_MAX_ITEMS
    if overflow > 0:
        oldest = sorted(_pending_magnet_picks.items(), key=lambda item: float(item[1].get("created_at") or 0))[:overflow]
        for token, _ in oldest:
            _pending_magnet_picks.pop(token, None)
    if expired or overflow > 0:
        _save_pending_magnet_results()


def _load_pending_magnet_results() -> None:
    if _pending_magnet_picks:
        return
    try:
        payload = get_flow(_PENDING_MAGNET_FLOW)
    except Exception:
        return
    raw_items = payload.get("items") or {}
    if not isinstance(raw_items, dict):
        return
    for token, item in raw_items.items():
        if not isinstance(item, dict):
            continue
        results = []
        for result in item.get("results") or []:
            if isinstance(result, dict):
                results.append(
                    SearchResult(
                        title=str(result.get("title") or ""),
                        url=str(result.get("url") or result.get("link") or ""),
                        source=str(result.get("source") or "tg_bot"),
                        message_id=result.get("message_id"),
                        context=str(result.get("context") or ""),
                        priority=int(result.get("priority") or 0),
                    )
                )
        _pending_magnet_picks[str(token)] = {
            "created_at": item.get("created_at") or 0,
            "detail": item.get("detail") or {},
            "results": results,
        }


def _save_pending_magnet_results() -> None:
    items: dict[str, Any] = {}
    for token, item in _pending_magnet_picks.items():
        results = []
        for result in item.get("results") or []:
            results.append(asdict(result) if is_dataclass(result) else dict(result))
        items[token] = {
            "created_at": item.get("created_at") or time.time(),
            "detail": item.get("detail") or {},
            "results": results,
        }
    try:
        save_flow(_PENDING_MAGNET_FLOW, {"items": items})
    except Exception:
        pass


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


