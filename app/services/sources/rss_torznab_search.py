from __future__ import annotations

from typing import Any

from app.services.link_parser import _download_link_key, _expanded_search_queries, _split_filter_words
from app.services.sources.rss_torznab_fetch_source import RssTorznabFetchSourceMixin
from app.services.sources.rss_torznab_search_groups import RssTorznabSearchGroupsMixin
from app.services.types import SearchResult


class RssTorznabSearchMixin(RssTorznabSearchGroupsMixin, RssTorznabFetchSourceMixin):
    def _source_matches_filters(self, source: dict[str, Any], text: str) -> bool:
        raw = text.casefold()
        required_keywords = _split_filter_words(source.get("keywords"))
        quality_keywords = _split_filter_words(source.get("quality"))
        if required_keywords and not all(keyword.casefold() in raw for keyword in required_keywords):
            return False
        if quality_keywords and not any(keyword.casefold() in raw for keyword in quality_keywords):
            return False
        return True

    def _search_queries(self, title: str, keywords: list[str]) -> list[str]:
        return _expanded_search_queries(title, keywords)

    def _dedupe_results(self, results: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[tuple[str, tuple[str, str]]] = set()
        for result in results:
            key = (result.source, _download_link_key(result.url))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped
