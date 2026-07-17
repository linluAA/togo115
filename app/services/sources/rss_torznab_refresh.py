from __future__ import annotations

import time

import httpx

from app.db import add_log
from app.services.link import _expanded_search_queries
from app.services.sources.rss_torznab_refresh_state import RssTorznabRefreshStateMixin
from app.services.types import SearchResult


class RssTorznabRefreshMixin(RssTorznabRefreshStateMixin):
    async def fetch_due_sources(self, queries: list[str] | None = None) -> list[SearchResult]:
        now = time.time()
        sources = self._due_sources()
        results: list[SearchResult] = []
        updated = False
        search_queries = _refresh_search_queries(queries)
        for source in sources:
            source_queries = self._source_queries(source, search_queries)
            if not source_queries:
                continue
            async with httpx.AsyncClient(proxy=self._source_proxy(source), timeout=25, follow_redirects=True) as client:
                for query in source_queries:
                    source_results = await self._fetch_source(source, query, client)
                    results.extend(source_results)
            source["last_checked_at"] = now
            updated = True
        if updated:
            self._persist_source_refresh_times(sources, now)
        results = self._dedupe_results(results)
        if results:
            add_log("info", "rss", "订阅源定时刷新完成", {"count": len(results), "sources": len(sources)})
        return results


def _refresh_search_queries(queries: list[str] | None) -> list[str]:
    search_queries: list[str] = []
    for query in queries or []:
        for expanded in _expanded_search_queries(str(query or ""), []):
            if expanded and expanded not in search_queries:
                search_queries.append(expanded)
    return search_queries


