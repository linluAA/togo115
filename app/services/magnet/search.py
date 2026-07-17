from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from app.db import add_log
from app.services.adapters.media import TmdbAdapter
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.magnet.cache import _cached_magnet_search, _store_magnet_search_cache
from app.services.magnet.constants import (
    TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS,
    TG_BOT_MAGNET_DETAIL_LIMIT,
    TG_BOT_MAGNET_FAST_RESPONSE_SECONDS,
    TG_BOT_MAGNET_LIMIT,
    TG_BOT_MAGNET_SOURCE_CONCURRENCY,
    TG_BOT_MAGNET_SOURCE_QUERY_LIMIT,
    TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS,
    TG_BOT_MAGNET_TIMEOUT_SECONDS,
)
from app.services.magnet.ranking import (
    _is_magnet_result,
    _query_without_year,
    _rank_magnet_results,
    _search_keywords,
    _search_title,
    _subscription_from_detail,
)

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


