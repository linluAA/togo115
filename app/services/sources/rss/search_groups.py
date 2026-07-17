from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.db import add_log
from app.services.types import SearchResult


RSS_SOURCE_CONCURRENCY = 3


class RssTorznabSearchGroupsMixin:
    async def search_history_by_source(self, title: str, keywords: list[str], query_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sources = self._sources()
        if not sources:
            add_log("debug", "rss", "没有启用的订阅源/磁力源，跳过搜索", {"title": title})
            return []
        groups: list[dict[str, Any]] = []
        queries = self._search_queries(title, keywords)
        for source in sources:
            source_results = await self._fetch_source_for_queries(source, queries, query_context) if query_context else await self._fetch_source_for_queries(source, queries)
            if source_results:
                groups.append({"source": source, "priority": self._source_priority(source), "results": source_results})
        count = sum(len(group["results"]) for group in groups)
        add_log("info", "rss", "订阅源搜索完成", {"count": count, "sources": len(sources), "title": title})
        return groups

    async def search_history_by_priority_until_match(
        self,
        title: str,
        keywords: list[str],
        matcher: Callable[[SearchResult], bool],
        query_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        sources = self._sources()
        if not sources:
            add_log("debug", "rss", "没有启用的订阅源/磁力源，跳过搜索", {"title": title})
            return []
        # Compact queries for faster fallback; full expansion remains for exhaustive search_history.
        queries = self._priority_search_queries(title, keywords)
        groups: list[dict[str, Any]] = []
        state = _PrioritySearchState()
        for wave in _priority_waves(sources, self._source_priority):
            if state.priority_matched and state.current_priority is not None:
                # Already matched a higher (or equal completed) priority wave.
                break
            priority = wave[0]
            wave_sources = wave[1]
            state.begin_priority(priority)
            wave_groups, searched, matched = await self._search_priority_wave(
                wave_sources,
                queries,
                matcher,
                query_context,
            )
            state.searched_sources += searched
            groups.extend(wave_groups)
            if matched:
                state.priority_matched = True
                # First usable hit ends the whole fallback search (skip lower priorities).
                break
        _log_priority_search_done(groups, state, title, queries=queries)
        return groups

    async def _search_priority_wave(
        self,
        sources: list[dict[str, Any]],
        queries: list[str],
        matcher: Callable[[SearchResult], bool],
        query_context: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Fetch same-priority sources concurrently; cancel remaining after first usable hit."""
        if not sources:
            return [], 0, False
        semaphore = asyncio.Semaphore(RSS_SOURCE_CONCURRENCY)
        groups: list[dict[str, Any]] = []
        searched = 0
        matched = False

        async def fetch_one(source: dict[str, Any]) -> tuple[dict[str, Any], list[SearchResult] | Exception]:
            async with semaphore:
                try:
                    if query_context:
                        results = await self._fetch_source_for_queries(source, queries, query_context)
                    else:
                        results = await self._fetch_source_for_queries(source, queries)
                    return source, results
                except Exception as exc:
                    return source, exc

        tasks = {asyncio.create_task(fetch_one(source)): source for source in sources}
        pending: set[asyncio.Task] = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    searched += 1
                    source, results = task.result()
                    if isinstance(results, Exception):
                        add_log(
                            "warning",
                            "rss",
                            "订阅源/磁力并发搜索失败，已跳过",
                            {
                                "source": source.get("name"),
                                "error": str(results),
                                "error_type": type(results).__name__,
                            },
                        )
                        continue
                    if not results:
                        continue
                    priority = self._source_priority(source)
                    groups.append({"source": source, "priority": priority, "results": results})
                    if _any_result_matches(source, results, matcher):
                        matched = True
                if matched:
                    await _cancel_pending(pending)
                    break
        finally:
            await _cancel_pending(pending)
        return groups, searched, matched

    async def search_history(self, title: str, keywords: list[str], query_context: dict[str, Any] | None = None) -> list[SearchResult]:
        groups = await self.search_history_by_source(title, keywords, query_context)
        results = [result for group in groups for result in group["results"]]
        return self._dedupe_results(results)


class _PrioritySearchState:
    def __init__(self) -> None:
        self.current_priority: int | None = None
        self.priority_matched = False
        self.searched_sources = 0

    def begin_priority(self, priority: int) -> None:
        self.current_priority = priority
        self.priority_matched = False

    def should_stop(self, priority: int) -> bool:
        # Kept for tests/backward compatibility with older call sites.
        if self.current_priority is not None and priority != self.current_priority and self.priority_matched:
            return True
        if self.current_priority is None or priority != self.current_priority:
            self.current_priority = priority
            self.priority_matched = False
        return False


def _priority_waves(sources: list[dict[str, Any]], priority_fn) -> list[tuple[int, list[dict[str, Any]]]]:
    waves: list[tuple[int, list[dict[str, Any]]]] = []
    current_priority: int | None = None
    bucket: list[dict[str, Any]] = []
    for source in sources:
        priority = int(priority_fn(source) or 0)
        if current_priority is None:
            current_priority = priority
            bucket = [source]
            continue
        if priority == current_priority:
            bucket.append(source)
            continue
        waves.append((current_priority, bucket))
        current_priority = priority
        bucket = [source]
    if current_priority is not None and bucket:
        waves.append((current_priority, bucket))
    return waves


async def _cancel_pending(pending: set[asyncio.Task]) -> None:
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def _any_result_matches(source: dict[str, Any], results: list[SearchResult], matcher: Callable[[SearchResult], bool]) -> bool:
    for result in results:
        try:
            if matcher(result):
                return True
        except Exception as exc:
            add_log(
                "warning",
                "rss",
                "订阅源/磁力结果可用性判断异常，已跳过单条结果",
                {
                    "source": source.get("name"),
                    "title": str(getattr(result, "title", "") or "")[:120],
                    "url": str(getattr(result, "url", "") or "")[:200],
                    "error": str(exc),
                },
            )
    return False


def _log_priority_search_done(
    groups: list[dict[str, Any]],
    state: _PrioritySearchState,
    title: str,
    *,
    queries: list[str] | None = None,
) -> None:
    count = sum(len(group["results"]) for group in groups)
    add_log(
        "info",
        "rss",
        "订阅源按优先级搜索完成",
        {
            "count": count,
            "sources": state.searched_sources,
            "title": title,
            "queries": list(queries or [])[:4],
            "matched_priority": state.current_priority if state.priority_matched else None,
        },
    )
