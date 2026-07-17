from __future__ import annotations

import asyncio
import time
from typing import Any

from app.db import add_log
from app.services.adapters.media import TmdbAdapter
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.magnet.cache import _cached_magnet_search, _store_magnet_search_cache
from app.services.magnet.constants import (
    TG_BOT_MAGNET_FAST_RESPONSE_SECONDS,
    TG_BOT_MAGNET_LIMIT,
    TG_BOT_MAGNET_TIMEOUT_SECONDS,
)
from app.services.magnet.ranking import (
    _detail_title,
    _rank_magnet_results,
    _search_keywords,
    _search_title,
    _subscription_from_detail,
)
from app.services.magnet.search_fetch import (
    _fetch_priority_sources,
    _fetch_priority_sources_until_ranked,
)
from app.services.magnet.search_queries import (
    _fast_magnet_query_batches,
    _fast_magnet_queries,
    _fast_source_options,
    _query_without_year,
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
        add_log("warning", "tg_bot", "TG Bot 磁力搜索超时", {"title": title, "tmdb_id": tmdb_id, "timeout": TG_BOT_MAGNET_TIMEOUT_SECONDS})
        return detail, []
    except Exception as exc:
        add_log("warning", "tg_bot", "TG Bot 磁力搜索失败", {"title": title, "tmdb_id": tmdb_id, "error": str(exc)})
        return detail, []

    ranked = _rank_magnet_results(subscription, candidates)
    if not ranked:
        recovery_candidates = await _search_builtin_recovery_candidates(adapter, _search_title(detail), keywords, subscription, limit)
        if recovery_candidates:
            candidates.extend(recovery_candidates)
            ranked = _rank_magnet_results(subscription, candidates)
    limited = ranked[:limit]
    _store_magnet_search_cache(media_type, tmdb_id, limit, detail, limited)
    add_log("info", "tg_bot", "TG Bot 磁力搜索完成", {"title": title, "tmdb_id": tmdb_id, "candidates": len(candidates), "matched": len(ranked)})
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
        add_log("debug", "tg_bot", "TG Bot 磁力搜索没有可用订阅源", {"title": title})
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


# Re-export helpers so magnet.__getattr__ and patches keep working.
from app.services.magnet.search_fetch import (  # noqa: E402
    _fetch_priority_sources,
    _fetch_priority_sources_until_ranked,
)
from app.services.magnet.search_queries import (  # noqa: E402
    _fast_magnet_queries,
    _fast_magnet_query_batches,
    _fast_source_options,
    _query_without_year,
)
