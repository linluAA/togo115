from __future__ import annotations

from typing import Any

from app.services.link import download_link_key, expanded_search_queries, split_filter_words, years_from_text, compact_search_text
from app.services.sources.rss.fetch_source import RssTorznabFetchSourceMixin
from app.services.sources.rss.search_groups import RssTorznabSearchGroupsMixin
from app.services.types import SearchResult


# Keep remote magnet/RSS query sets small; full expansion is expensive on slow sites.
RSS_PRIORITY_QUERY_LIMIT = 2


class RssTorznabSearchMixin(RssTorznabSearchGroupsMixin, RssTorznabFetchSourceMixin):
    def _source_matches_filters(self, source: dict[str, Any], text: str) -> bool:
        raw = text.casefold()
        required_keywords = split_filter_words(source.get("keywords"))
        quality_keywords = split_filter_words(source.get("quality"))
        if required_keywords and not all(keyword.casefold() in raw for keyword in required_keywords):
            return False
        if quality_keywords and not any(keyword.casefold() in raw for keyword in quality_keywords):
            return False
        return True

    def _search_queries(self, title: str, keywords: list[str], *, max_queries: int | None = None) -> list[str]:
        limit = max_queries if max_queries is not None else 16
        return expanded_search_queries(title, keywords, max_queries=max(1, int(limit)))

    def _priority_search_queries(self, title: str, keywords: list[str]) -> list[str]:
        """Compact query set for subscription fallback / priority search."""
        queries = self._search_queries(title, keywords, max_queries=6)
        return _prefer_compact_queries(queries, limit=RSS_PRIORITY_QUERY_LIMIT)

    def _dedupe_results(self, results: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[tuple[str, tuple[str, str]]] = set()
        for result in results:
            key = (result.source, download_link_key(result.url))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped


def _prefer_compact_queries(queries: list[str], *, limit: int = 2) -> list[str]:
    cleaned = [str(item or "").strip() for item in queries if str(item or "").strip()]
    if not cleaned:
        return []

    def sort_key(item: str) -> tuple[int, int, int, int]:
        compact = compact_search_text(item) or ""
        has_year = 1 if years_from_text(item) else 0
        has_space = 1 if any(ch.isspace() for ch in item) else 0
        token_count = max(1, len([part for part in item.split() if part]))
        return (has_year, has_space, token_count, len(compact))

    selected: list[str] = []
    seen: set[str] = set()
    for query in sorted(cleaned, key=sort_key):
        key = compact_search_text(query) or ""
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(query)
        if len(selected) >= max(1, limit):
            break
    return selected
