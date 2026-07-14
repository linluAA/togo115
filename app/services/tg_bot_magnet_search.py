from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from app.db import add_log
from app.services.adapters.media import TmdbAdapter
from app.services.integration_state import get_flow, save_flow
from app.services.link_downloads import _download_link_key, is_valid_download_link
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.subscription.match.matching import result_matches_subscription
from app.services.subscription.match.result_utils import result_text
from app.services.subscription.match.text_utils import compact_match_text, years_from_text


TG_BOT_MAGNET_LIMIT = 5
TG_BOT_MAGNET_TIMEOUT_SECONDS = 15
TG_BOT_MAGNET_FAST_RESPONSE_SECONDS = 10.5
TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS = 10.5
TG_BOT_MAGNET_SOURCE_CONCURRENCY = 4
TG_BOT_MAGNET_SOURCE_QUERY_LIMIT = 2
TG_BOT_MAGNET_DETAIL_LIMIT = 3
TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS = 0.15
TG_BOT_MAGNET_PICK_TTL_SECONDS = 1800
TG_BOT_MAGNET_PICK_MAX_ITEMS = 50
TG_BOT_MAGNET_CACHE_TTL_SECONDS = 1800
TG_BOT_MAGNET_CACHE_MAX_ITEMS = 80

_pending_magnet_picks: dict[str, dict[str, Any]] = {}
_magnet_search_cache: dict[str, dict[str, Any]] = {}
_PENDING_MAGNET_FLOW = "tg_bot_magnet_picks"
_MAGNET_SEARCH_CACHE_FLOW = "tg_bot_magnet_search_cache"


async def tmdb_search_choices(query: str, limit: int = 8) -> list[dict[str, Any]]:
    results = await TmdbAdapter().search(query, "multi")
    return [item for item in results if item.get("media_type") in ("tv", "movie")][:limit]


async def search_magnets_for_tmdb(media_type: str, tmdb_id: int, limit: int = TG_BOT_MAGNET_LIMIT) -> tuple[dict[str, Any], list[SearchResult]]:
    cached = _cached_magnet_search(media_type, tmdb_id, limit)
    if cached:
        add_log("info", "tg_bot", "TG Bot 磁力搜索命中缓存", {"media_type": media_type, "tmdb_id": tmdb_id, "count": len(cached[1])})
        return cached
    detail = dict(await TmdbAdapter().detail(media_type, tmdb_id))
    detail["media_type"] = media_type
    title = _detail_title(detail)
    if not title:
        return detail, []
    subscription = _subscription_from_detail(media_type, tmdb_id, detail)
    keywords = _search_keywords(detail)
    adapter = RssTorznabAdapter()
    try:
        candidates = await _search_priority_magnet_candidates(adapter, _search_title(detail), keywords, subscription, limit)
    except asyncio.TimeoutError:
        add_log("warning", "tg_bot", "TG Bot \u78c1\u529b\u641c\u7d22\u8d85\u65f6", {"title": title, "tmdb_id": tmdb_id, "timeout": TG_BOT_MAGNET_TIMEOUT_SECONDS})
        return detail, []
    except Exception as exc:
        add_log("warning", "tg_bot", "TG Bot \u78c1\u529b\u641c\u7d22\u5931\u8d25", {"title": title, "tmdb_id": tmdb_id, "error": str(exc)})
        return detail, []

    ranked = _rank_magnet_results(subscription, candidates)
    if not ranked:
        recovery_candidates = await _search_builtin_recovery_candidates(adapter, _search_title(detail), keywords, subscription, limit)
        if recovery_candidates:
            candidates.extend(recovery_candidates)
            ranked = _rank_magnet_results(subscription, candidates)
    limited = ranked[:limit]
    _store_magnet_search_cache(media_type, tmdb_id, limit, detail, limited)
    add_log("info", "tg_bot", "TG Bot \u78c1\u529b\u641c\u7d22\u5b8c\u6210", {"title": title, "tmdb_id": tmdb_id, "candidates": len(candidates), "matched": len(ranked)})
    return detail, limited


async def _search_priority_magnet_candidates(
    adapter: RssTorznabAdapter,
    title: str,
    keywords: list[str],
    subscription: dict[str, Any],
    limit: int,
) -> list[SearchResult]:
    sources = adapter._sources()
    if not sources:
        add_log("debug", "tg_bot", "TG Bot \u78c1\u529b\u641c\u7d22\u6ca1\u6709\u53ef\u7528\u8ba2\u9605\u6e90", {"title": title})
        return []
    query_batches = _fast_magnet_query_batches(title, keywords)
    candidates: list[SearchResult] = []
    searched_sources = 0
    deadline = time.perf_counter() + TG_BOT_MAGNET_FAST_RESPONSE_SECONDS
    for queries in query_batches:
        if len(_rank_magnet_results(subscription, candidates)) >= limit:
            break
        searched_sources += await _search_priority_batch(adapter, sources, queries, subscription, limit, candidates, deadline)
    return candidates


async def _search_priority_batch(
    adapter: RssTorznabAdapter,
    sources: list[dict[str, Any]],
    queries: list[str],
    subscription: dict[str, Any],
    limit: int,
    candidates: list[SearchResult],
    deadline: float,
) -> int:
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        return 0
    source_candidates, searched_sources, early_hit = await _fetch_priority_sources_until_ranked(
        adapter,
        sources,
        queries,
        subscription,
        limit,
        candidates,
        timeout=remaining,
        min_matches=1,
    )
    candidates.extend(source_candidates)
    if early_hit:
        add_log(
            "debug",
            "tg_bot",
            "TG Bot 磁力搜索已命中可用结果，提前停止等待慢源",
            {"queries": queries, "sources": searched_sources},
        )
    return searched_sources


async def _search_builtin_recovery_candidates(
    adapter: RssTorznabAdapter,
    title: str,
    keywords: list[str],
    subscription: dict[str, Any],
    limit: int,
) -> list[SearchResult]:
    configured_keys = {adapter._source_dedupe_key(source) for source in adapter._sources()}
    recovery_sources = [
        source
        for source in adapter.BUILTIN_SOURCES
        if adapter._source_dedupe_key(source) not in configured_keys and adapter._site_plugin_id(source) == "qmp4"
    ]
    if not recovery_sources:
        return []
    queries = _fast_magnet_queries(title, keywords)
    candidates, searched, _ = await _fetch_priority_sources_until_ranked(
        adapter,
        recovery_sources,
        queries,
        subscription,
        limit,
        [],
        timeout=TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS,
    )
    ranked = _rank_magnet_results(subscription, candidates)
    add_log(
        "info" if ranked else "debug",
        "tg_bot",
                "TG Bot 内置订阅源补搜完成",
        {"title": title, "sources": searched, "candidates": len(candidates), "matched": len(ranked)},
    )
    return candidates


async def _fetch_priority_sources_until_ranked(
    adapter: RssTorznabAdapter,
    sources: list[dict[str, Any]],
    queries: list[str],
    subscription: dict[str, Any],
    limit: int,
    existing_candidates: list[SearchResult] | None = None,
    timeout: float | None = None,
    min_matches: int | None = None,
) -> tuple[list[SearchResult], int, bool]:
    if not sources:
        return [], 0, False
    semaphore = asyncio.Semaphore(TG_BOT_MAGNET_SOURCE_CONCURRENCY)
    candidates: list[SearchResult] = []
    searched_sources = 0

    async def fetch(source: dict[str, Any]) -> tuple[dict[str, Any], list[SearchResult] | Exception]:
        async with semaphore:
            try:
                results = await adapter._fetch_source_for_queries(_fast_source_options(source), queries[:TG_BOT_MAGNET_SOURCE_QUERY_LIMIT])
                return source, results
            except Exception as exc:
                return source, exc

    tasks = [asyncio.create_task(fetch(source)) for source in sources]
    pending: set[asyncio.Task] = set(tasks)
    deadline = time.perf_counter() + max(0.1, timeout or TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS)
    try:
        while pending:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                done = set()
            else:
                done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await _cancel_slow_magnet_sources(pending, timeout)
                return candidates, searched_sources, False
            searched_sources += await _merge_completed_magnet_sources(done, candidates)
            required_matches = max(1, min_matches or limit)
            if len(_rank_magnet_results(subscription, [*(existing_candidates or []), *candidates])) >= required_matches:
                await _cancel_pending_magnet_sources(pending)
                return candidates, searched_sources, True
        return candidates, searched_sources, False
    finally:
        await _cancel_pending_magnet_sources(pending)


async def _merge_completed_magnet_sources(done: set[asyncio.Task], candidates: list[SearchResult]) -> int:
    searched_sources = 0
    for task in done:
        searched_sources += 1
        source, results = task.result()
        if isinstance(results, Exception):
            add_log(
                "warning",
                "tg_bot",
                "TG Bot 磁力订阅源搜索失败",
                {"source": source.get("name") or "订阅源", "error": str(results), "error_type": type(results).__name__},
            )
            continue
        candidates.extend(result for result in results if _is_magnet_result(result))
    return searched_sources


async def _cancel_slow_magnet_sources(pending: set[asyncio.Task], timeout: float | None) -> None:
    pending_count = len(pending)
    await _cancel_pending_magnet_sources(pending)
    add_log(
        "warning",
        "tg_bot",
        "TG Bot 磁力订阅源搜索超时，已取消慢源",
        {"timeout": round(timeout or TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS, 2), "pending": pending_count},
    )


async def _cancel_pending_magnet_sources(pending: set[asyncio.Task]) -> None:
    for item in pending:
        item.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _fetch_priority_sources(adapter: RssTorznabAdapter, sources: list[dict[str, Any]], queries: list[str]) -> list[list[SearchResult]]:
    semaphore = asyncio.Semaphore(TG_BOT_MAGNET_SOURCE_CONCURRENCY)

    async def fetch(source: dict[str, Any]) -> list[SearchResult]:
        async with semaphore:
            return await adapter._fetch_source_for_queries(_fast_source_options(source), queries[:TG_BOT_MAGNET_SOURCE_QUERY_LIMIT])

    responses = await asyncio.gather(*(fetch(source) for source in sources), return_exceptions=True)
    groups: list[list[SearchResult]] = []
    for source, response in zip(sources, responses):
        if isinstance(response, Exception):
            add_log(
                "warning",
                "tg_bot",
                "TG Bot 磁力订阅源搜索失败",
                {"source": source.get("name") or "订阅源", "error": str(response), "error_type": type(response).__name__},
            )
            groups.append([])
            continue
        groups.append(response)
    return groups


def _fast_magnet_query_batches(title: str, keywords: list[str]) -> list[list[str]]:
    queries = _fast_magnet_queries(title, keywords)
    if not queries:
        return []
    first = queries[:1]
    second = queries[1:TG_BOT_MAGNET_SOURCE_QUERY_LIMIT + 1]
    return [batch for batch in (first, second) if batch]


def _fast_magnet_queries(title: str, keywords: list[str]) -> list[str]:
    queries: list[str] = []

    def add(value: str | None) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if normalized and normalized not in queries:
            queries.append(normalized)

    add(title)
    add(_query_without_year(title))
    for keyword in keywords:
        add(keyword)
        add(_query_without_year(keyword))
    return queries[:4]


def _query_without_year(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"[\(（\[【]\s*(?:19|20)\d{2}\s*[\)）\]】]", " ", text)
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _fast_source_options(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **source,
        "_fast_detail_limit": TG_BOT_MAGNET_DETAIL_LIMIT,
        "_bt1207_detail_delay": TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS,
        "_parallel_details": True,
        "_request_timeout": min(TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS, 8.0),
    }


def magnet_results_reply(detail: dict[str, Any], results: list[SearchResult]) -> str:
    title = _detail_title(detail) or "\u672a\u547d\u540d"
    year = _detail_year(detail) or "\u672a\u77e5\u5e74\u4efd"
    if not results:
        return f"{title} ({year})\n\u6ca1\u6709\u4ece\u78c1\u529b\u8ba2\u9605\u6e90\u627e\u5230\u5339\u914d\u7ed3\u679c\u3002"
    lines = [f"{title} ({year})", f"\u627e\u5230 {len(results)} \u6761\u6700\u5339\u914d\u78c1\u529b\uff1a"]
    for index, result in enumerate(results, start=1):
        name = str(result.title or "\u78c1\u529b\u8d44\u6e90").strip()[:80]
        source = _display_source(result.source)
        size = _resource_size(result) or "\u672a\u77e5"
        lines.append(f"\n{index}. {name}\n\u5927\u5c0f\uff1a{size}\n\u6765\u6e90\uff1a{source}\n{result.url}")
    return "\n".join(lines)


def magnet_results_reply_markup(detail: dict[str, Any], results: list[SearchResult]) -> dict[str, Any]:
    token = _store_pending_magnet_results(detail, results)
    buttons = [[]]
    for index, result in enumerate(results, start=1):
        buttons[0].append({"text": str(index), "callback_data": f"magpick:{token}:{index - 1}"})
    return {"inline_keyboard": buttons}


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


def _display_source(source: str | None) -> str:
    value = str(source or "\u8ba2\u9605\u6e90").strip()
    if ":" in value:
        value = value.split(":", 1)[1] or value
    return value[:40]


def _resource_size(result: Any) -> str:
    text = "\n".join(str(part or "") for part in (_result_attr(result, "title"), _result_attr(result, "context"), _result_attr(result, "url")))
    match = re.search(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(TiB|GiB|MiB|TB|GB|MB|T|G|M)(?![A-Za-z])", text, re.I)
    if not match:
        return ""
    number = match.group(1)
    unit = match.group(2).upper()
    unit = {"GIB": "GB", "MIB": "MB", "TIB": "TB", "G": "GB", "M": "MB", "T": "TB"}.get(unit, unit)
    return f"{number} {unit}"


def _result_attr(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name) or result.get("link") if name == "url" else result.get(name)
    return getattr(result, name, None)


def _detail_title(detail: dict[str, Any]) -> str:
    return str(detail.get("name") or detail.get("title") or "").strip()


def _detail_year(detail: dict[str, Any]) -> str:
    return str(detail.get("first_air_date") or detail.get("release_date") or "")[:4]


def _search_title(detail: dict[str, Any]) -> str:
    title = _detail_title(detail)
    year = _detail_year(detail)
    return f"{title} {year}".strip()


def _search_keywords(detail: dict[str, Any]) -> list[str]:
    title = _detail_title(detail)
    original = str(detail.get("original_name") or detail.get("original_title") or "").strip()
    return [item for item in dict.fromkeys([title, original]) if item]


def _subscription_from_detail(media_type: str, tmdb_id: int, detail: dict[str, Any]) -> dict[str, Any]:
    title = _detail_title(detail)
    year = _detail_year(detail)
    return {
        "id": 0,
        "title": title,
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "release_year": int(year) if year.isdigit() else None,
        "keywords": [title],
        "search_aliases": _search_keywords(detail),
        "quality_rules": {},
        "tmdb_total_count": detail.get("number_of_episodes") or 0,
        "tmdb_seasons": detail.get("seasons") or [],
        "emby_episode_keys": [],
        "emby_count": 0,
        "in_library": False,
    }


def _is_magnet_result(result: SearchResult) -> bool:
    url = str(getattr(result, "url", "") or "").strip()
    return url.casefold().startswith("magnet:?") and is_valid_download_link(url)


def _rank_magnet_results(subscription: dict[str, Any], results: list[SearchResult]) -> list[SearchResult]:
    seen: set[tuple[str, str]] = set()
    scored: list[tuple[int, int, int, SearchResult]] = []
    for index, result in enumerate(results):
        key = _download_link_key(result.url)
        if key in seen:
            continue
        seen.add(key)
        score = _result_score(subscription, result)
        if score <= 0:
            continue
        scored.append((score, int(getattr(result, "priority", 0) or 0), -index, result))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in scored]


def _result_score(subscription: dict[str, Any], result: SearchResult) -> int:
    text = result_text(result)
    if not _bot_title_or_alias_matches(subscription, text):
        return 0
    year = subscription.get("release_year")
    years = years_from_text(text)
    if year and years and int(year) not in years:
        return 0
    try:
        if result_matches_subscription(subscription, result):
            return 100 + _quality_score(text)
    except Exception:
        pass
    return 60 + _quality_score(text)



def _bot_title_or_alias_matches(subscription: dict[str, Any], text: str) -> bool:
    raw_text = str(text or "")
    compact_text = compact_match_text(raw_text)
    candidates = [subscription.get("title"), *(subscription.get("search_aliases") or [])]
    for item in candidates:
        term = _query_without_year(str(item or "")).strip()
        compact = compact_match_text(term)
        if not compact:
            continue
        if _contains_cjk(term):
            if _cjk_title_match(term, raw_text):
                return True
            continue
        if _latin_title_match(compact, compact_text):
            return True
    return False


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))


def _cjk_title_match(term: str, text: str) -> bool:
    normalized_term = re.sub(r"\s+", "", term)
    normalized_text = re.sub(r"\s+", "", text or "")
    if not normalized_term:
        return False
    start = 0
    while True:
        index = normalized_text.find(normalized_term, start)
        if index < 0:
            return False
        before = normalized_text[index - 1] if index > 0 else ""
        after_index = index + len(normalized_term)
        after = normalized_text[after_index] if after_index < len(normalized_text) else ""
        if _cjk_prefix_boundary(before) and _cjk_suffix_boundary(after):
            return True
        start = index + 1


def _cjk_prefix_boundary(char: str) -> bool:
    return not char or not re.match(r"[\u3400-\u9fffA-Za-z0-9]", char)


def _cjk_suffix_boundary(char: str) -> bool:
    if not char:
        return True
    if char.isdigit():
        return True
    return bool(re.match(r"[\s\[\]\(\)【】（）._\-/·]", char))


def _latin_title_match(term: str, compact_text: str) -> bool:
    if not term:
        return False
    start = 0
    while True:
        index = compact_text.find(term, start)
        if index < 0:
            return False
        before = compact_text[index - 1] if index > 0 else ""
        after_index = index + len(term)
        after = compact_text[after_index] if after_index < len(compact_text) else ""
        before_is_word = before.isascii() and before.isalnum()
        after_is_word = after.isascii() and after.isalnum()
        if not before_is_word and not after_is_word:
            return True
        if index == 0 and (not after or after.isdigit()):
            return True
        start = index + 1


def _quality_score(text: str) -> int:
    value = text.casefold()
    score = 0
    for pattern, points in ((r"2160p|4k|uhd", 8), (r"1080p", 6), (r"web-?dl|webrip", 4), (r"bluray|blu-ray", 3), (r"h\.265|x265|hevc", 2)):
        if re.search(pattern, value):
            score += points
    return score
