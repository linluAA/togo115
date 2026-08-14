from __future__ import annotations

import re
from typing import Any

from app.services.adapters.telegram.scan.extract_cache import set_cached_message_extract
from app.services.link import context_for_115_link, context_for_ed2k_link, extract_115_links, local_text_matches_query
from app.services.types import SearchResult
from app.services.adapters.telegram.scan.message_titles import (
    _enrich_title_with_episode_marker,
    _metadata_field_line,
    _telegram_resource_title,
)


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
            is_ed2k = link.casefold().startswith("ed2k://")
            if is_ed2k:
                scoped = context_for_ed2k_link(context, link) or context
            else:
                scoped = context_for_115_link(context, link, max(len(link_contexts), 2)) or context
            scoped = _restore_query_title_context(context, scoped, match_queries)
            title = _telegram_resource_title(scoped)
            # ed2k links carry episode info in the filename itself; skip the
            # strict text-level query match to avoid rejecting English-named
            # files against Chinese subscription queries. The subscription
            # matching pipeline handles episode-level filtering downstream.
            if not is_ed2k and not any(local_text_matches_query(scoped, query) for query in match_queries):
                continue
            if title and not str(title).startswith("Telegram ") and not is_ed2k and not any(local_text_matches_query(title, query) for query in match_queries):
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


CONTEXT_TITLE_NOISE_RE = re.compile(
    r"(?:地区|国家|标签|简介|主演|评分|类型|分类|大小|质量|语言|字幕|TMDB\s*ID|链接|提取码|访问码|密码)",
    re.I,
)


def _restore_query_title_context(context: str, scoped: str, match_queries: list[str] | None) -> str:
    if not match_queries or any(local_text_matches_query(scoped, query) for query in match_queries):
        return scoped
    title = _query_title_line(context, match_queries)
    if not title:
        return scoped
    if title in scoped:
        return scoped
    return f"{title}\n{scoped}".strip()


def _query_title_line(context: str, match_queries: list[str]) -> str:
    for line in str(context or "").splitlines():
        value = line.strip()
        if not value or extract_115_links(value) or _metadata_field_line(value) or CONTEXT_TITLE_NOISE_RE.search(value):
            continue
        if any(local_text_matches_query(value, query) for query in match_queries):
            return value[:160]
    return ""
