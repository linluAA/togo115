from __future__ import annotations

from typing import Any, Callable

from app.db import add_log
from app.services.types import SearchResult


class RssTorznabSearchGroupsMixin:
    async def search_history_by_source(self, title: str, keywords: list[str]) -> list[dict[str, Any]]:
        sources = self._sources()
        if not sources:
            add_log("debug", "rss", "没有启用的订阅源/磁力源，跳过搜索", {"title": title})
            return []
        groups: list[dict[str, Any]] = []
        queries = self._search_queries(title, keywords)
        for source in sources:
            source_results = await self._fetch_source_for_queries(source, queries)
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
    ) -> list[dict[str, Any]]:
        sources = self._sources()
        if not sources:
            add_log("debug", "rss", "没有启用的订阅源/磁力源，跳过搜索", {"title": title})
            return []
        groups: list[dict[str, Any]] = []
        queries = self._search_queries(title, keywords)
        state = _PrioritySearchState()
        for source in sources:
            priority = self._source_priority(source)
            if state.should_stop(priority):
                break
            source_results = await self._fetch_source_for_queries(source, queries)
            state.searched_sources += 1
            if not source_results:
                continue
            groups.append({"source": source, "priority": priority, "results": source_results})
            if _any_result_matches(source, source_results, matcher):
                state.priority_matched = True
        _log_priority_search_done(groups, state, title)
        return groups

    async def search_history(self, title: str, keywords: list[str]) -> list[SearchResult]:
        groups = await self.search_history_by_source(title, keywords)
        results = [result for group in groups for result in group["results"]]
        return self._dedupe_results(results)


class _PrioritySearchState:
    def __init__(self) -> None:
        self.current_priority: int | None = None
        self.priority_matched = False
        self.searched_sources = 0

    def should_stop(self, priority: int) -> bool:
        if self.current_priority is not None and priority != self.current_priority and self.priority_matched:
            return True
        if self.current_priority is None or priority != self.current_priority:
            self.current_priority = priority
            self.priority_matched = False
        return False


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


def _log_priority_search_done(groups: list[dict[str, Any]], state: _PrioritySearchState, title: str) -> None:
    count = sum(len(group["results"]) for group in groups)
    add_log(
        "info",
        "rss",
        "订阅源按优先级搜索完成",
        {
            "count": count,
            "sources": state.searched_sources,
            "title": title,
            "matched_priority": state.current_priority if state.priority_matched else None,
        },
    )
