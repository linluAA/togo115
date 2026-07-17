from __future__ import annotations

import time
from typing import Any

import httpx

from app.services.types import SearchResult


class RssTorznabCacheMixin:
    # Full hits stay long; empty/no-result queries use a short negative cache.
    EMPTY_SEARCH_CACHE_TTL_SECONDS = 120

    def _search_cache_key(self, source: dict[str, Any], query: str | None) -> tuple[str, str]:
        return (self._source_dedupe_key(source), str(query or ""))

    def _cached_source_results(self, source: dict[str, Any], query: str | None) -> list[SearchResult] | None:
        key = self._search_cache_key(source, query)
        cached = self._search_cache.get(key)
        if not cached:
            return None
        timestamp, results = cached
        ttl = self.EMPTY_SEARCH_CACHE_TTL_SECONDS if not results else self.SEARCH_CACHE_TTL_SECONDS
        if time.time() - timestamp > ttl:
            self._search_cache.pop(key, None)
            return None
        return list(results)

    def _store_source_results_cache(self, source: dict[str, Any], query: str | None, results: list[SearchResult]) -> None:
        if len(self._search_cache) > 768:
            now = time.time()
            expired = [key for key, (timestamp, _) in self._search_cache.items() if now - timestamp > self.SEARCH_CACHE_TTL_SECONDS]
            for key in expired:
                self._search_cache.pop(key, None)
            if len(self._search_cache) > 768:
                for key in list(self._search_cache)[:128]:
                    self._search_cache.pop(key, None)
        self._search_cache[self._search_cache_key(source, query)] = (time.time(), list(results))

    async def _fetch_source_for_queries(self, source: dict[str, Any], queries: list[str], query_context: dict[str, Any] | None = None) -> list[SearchResult]:
        results: list[SearchResult] = []
        source_queries = self._source_queries(source, queries)
        if not source_queries:
            return []
        async with httpx.AsyncClient(proxy=self._source_proxy(source), timeout=self._source_timeout(source), follow_redirects=True) as client:
            for index, query in enumerate(source_queries):
                cached = self._cached_source_results(source, query)
                if cached is not None:
                    results.extend(cached)
                else:
                    fetched = await self._fetch_source(source, query, client, query_context) if query_context else await self._fetch_source(source, query, client)
                    self._store_source_results_cache(source, query, fetched)
                    results.extend(fetched)
                # First non-empty query is usually enough for fallback recall; skip extra variants.
                if results and index + 1 < len(source_queries):
                    break
        return self._dedupe_results(results)

