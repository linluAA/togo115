from __future__ import annotations

from typing import Any

from app.services.adapters.telegram.scan.extract_cache import set_cached_message_extract
from app.services.link import context_for_115_link, local_text_matches_query
from app.services.types import SearchResult
from app.services.adapters.telegram.scan.message_titles import _enrich_title_with_episode_marker, _telegram_resource_title


class TelegramMessageLinkFilterMixin:
    def _dedupe_results(self, results: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[tuple[str, str | None, str]] = set()
        for result in results:
            key = (result.source, result.message_id, result.url)
            if key not in seen:
                seen.add(key)
                deduped.append(result)
        return deduped

    def _filter_cached_results_by_query(self, results: list[SearchResult], match_queries: list[str] | None) -> list[SearchResult]:
        if not match_queries:
            return results
        contexts = {result.url: result.context or result.title for result in results}
        allowed = set(self._filter_link_contexts_by_query(contexts, match_queries))
        return [result for result in results if result.url in allowed]

    def _filter_link_contexts_by_query(
        self,
        link_contexts: dict[str, str],
        match_queries: list[str] | None,
    ) -> dict[str, str]:
        if not match_queries:
            return link_contexts
        filtered: dict[str, str] = {}
        for link, context in link_contexts.items():
            scoped = context_for_115_link(context, link, max(len(link_contexts), 2)) or context
            title = _telegram_resource_title(scoped)
            if not any(local_text_matches_query(scoped, query) for query in match_queries):
                continue
            if title and not str(title).startswith("Telegram ") and not any(local_text_matches_query(title, query) for query in match_queries):
                continue
            filtered[link] = scoped
        return filtered

    def _finalize_message_extract(
        self,
        message: Any,
        source: str,
        link_contexts: dict[str, str],
        *,
        cacheable: bool,
        match_queries: list[str] | None = None,
    ) -> list[SearchResult]:
        filtered = self._filter_link_contexts_by_query(link_contexts, match_queries)
        results = self._search_results_from_contexts(message, source, filtered)
        if cacheable:
            # Cache unfiltered extract; query filtering is applied per search.
            set_cached_message_extract(
                source,
                getattr(message, "id", None),
                self._search_results_from_contexts(message, source, link_contexts),
            )
        return results

    def _search_results_from_contexts(self, message: Any, source: str, link_contexts: dict[str, str]) -> list[SearchResult]:
        return [
            SearchResult(
                title=_telegram_resource_title(context),
                url=link,
                source=str(source),
                message_id=str(getattr(message, "id", "")),
                context=context,
            )
            for link, context in link_contexts.items()
        ]
