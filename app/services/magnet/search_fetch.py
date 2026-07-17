from __future__ import annotations

import asyncio
import time
from typing import Any

from app.db import add_log
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.magnet.constants import (
    TG_BOT_MAGNET_GOOD_SCORE,
    TG_BOT_MAGNET_SOURCE_CONCURRENCY,
    TG_BOT_MAGNET_SOURCE_QUERY_LIMIT,
    TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS,
)
from app.services.magnet.ranking import _is_magnet_result, _rank_magnet_results, _result_score
from app.services.magnet.search_queries import _fast_source_options


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
            ranked = _rank_magnet_results(subscription, [*(existing_candidates or []), *candidates])
            if ranked:
                top = ranked[: max(1, required_matches)]
                good_enough = any(_result_score(subscription, item) >= TG_BOT_MAGNET_GOOD_SCORE for item in top)
                if len(ranked) >= required_matches and good_enough:
                    await _cancel_pending_magnet_sources(pending)
                    return candidates, searched_sources, True
                if len(ranked) >= max(required_matches, limit):
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
