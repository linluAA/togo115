from __future__ import annotations

import re
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.scan.message_candidates import (
    telegram_candidate_context_text,
    telegram_candidate_link_contexts,
)
from app.services.adapters.telegram.scan.extract_cache import (
    get_cached_message_extract,
    set_cached_message_extract,
)
from app.services.link import (
    _local_text_matches_query,
    context_for_115_link,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult
from app.services.adapters.telegram.scan.message_titles import _enrich_title_with_episode_marker, _telegram_resource_title


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramMessageLinkMixin:
    def _dedupe_results(self, results: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[tuple[str, str | None, str]] = set()
        for result in results:
            key = (result.source, result.message_id, result.url)
            if key not in seen:
                seen.add(key)
                deduped.append(result)
        return deduped

    async def _message_text_for_link_scan(self, client: TelegramClient | None, message: Any, entity: Any = None, match_queries: list[str] | None = None) -> str:
        texts: list[str] = []
        seen: set[str] = set()
        for related in await self._related_messages_for_link_scan(client, message, entity, match_queries):
            text = telegram_message_text(related)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return "\n".join(texts)

    async def _links_from_message(
        self,
        client: TelegramClient | None,
        message: Any,
        source: str,
        entity: Any = None,
        match_queries: list[str] | None = None,
        extra_texts: list[str] | None = None,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        # Cache only pure message extracts (no extra_texts), keyed by source+message_id.
        cacheable = not extra_texts
        message_id = getattr(message, "id", None)
        if cacheable:
            cached = get_cached_message_extract(source, message_id)
            if cached is not None:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 消息提取缓存命中",
                    {"source": source, "message_id": message_id, "links": len(cached), "total_ms": _elapsed_ms(started)},
                )
                return self._filter_cached_results_by_query(list(cached), match_queries)
        related_messages, related_ms = await self._timed_related_messages(client, message, entity, match_queries, extra_texts)
        message_text = self._combined_message_text(related_messages, extra_texts)
        link_contexts, direct_ms, direct_links = self._timed_direct_link_contexts(related_messages, extra_texts)
        # Fast path: message/context already has usable 115 links. Skip external pages and button clicks.
        if direct_links > 0:
            self._log_link_extraction(
                message,
                source,
                related_messages,
                link_contexts,
                message_text,
                {
                    "direct_links": direct_links,
                    "external_page_links": 0,
                    "button_links": 0,
                    "related_ms": related_ms,
                    "direct_ms": direct_ms,
                    "external_page_ms": 0,
                    "button_ms": 0,
                    "total_ms": _elapsed_ms(started),
                    "skipped_heavy_extract": 1,
                },
            )
            return self._finalize_message_extract(message, source, link_contexts, cacheable=cacheable, match_queries=match_queries)
        external_page_ms, text_page_links = await self._timed_external_page_contexts(message_text, link_contexts, direct_links)
        button_ms, button_links = await self._merge_button_link_contexts(related_messages, client, entity, extra_texts, link_contexts)
        self._log_link_extraction(message, source, related_messages, link_contexts, message_text, {
            "direct_links": direct_links,
            "external_page_links": max(text_page_links, 0),
            "button_links": button_links,
            "related_ms": related_ms,
            "direct_ms": direct_ms,
            "external_page_ms": external_page_ms,
            "button_ms": button_ms,
            "total_ms": _elapsed_ms(started),
            "skipped_heavy_extract": 0,
        })
        return self._finalize_message_extract(message, source, link_contexts, cacheable=cacheable, match_queries=match_queries)

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
            if not any(_local_text_matches_query(scoped, query) for query in match_queries):
                continue
            if title and not str(title).startswith("Telegram ") and not any(_local_text_matches_query(title, query) for query in match_queries):
                continue
            filtered[link] = scoped
        return filtered

    async def _timed_related_messages(self, client, message, entity, match_queries, extra_texts) -> tuple[list[Any], int]:
        started = time.perf_counter()
        related_messages = await self._messages_for_link_extraction(client, message, entity, match_queries, extra_texts)
        return related_messages, _elapsed_ms(started)

    def _timed_direct_link_contexts(self, related_messages: list[Any], extra_texts: list[str] | None) -> tuple[dict[str, str], int, int]:
        started = time.perf_counter()
        link_contexts = telegram_candidate_link_contexts(related_messages, extra_texts)
        return link_contexts, _elapsed_ms(started), len(link_contexts)

    async def _timed_external_page_contexts(self, message_text: str, link_contexts: dict[str, str], direct_links: int) -> tuple[int, int]:
        started = time.perf_counter()
        await self._collect_text_external_page_contexts(message_text, link_contexts)
        return _elapsed_ms(started), len(link_contexts) - direct_links

    async def _merge_button_link_contexts(self, related_messages: list[Any], client, entity, extra_texts, link_contexts: dict[str, str]) -> tuple[int, int]:
        started = time.perf_counter()
        button_links = 0
        for related in related_messages:
            if not getattr(related, "buttons", None):
                continue
            expanded_links = await self._click_buttons_for_links(related, client, entity)
            button_links += len(expanded_links)
            for link, button_text in expanded_links:
                context_source = "\n".join(part for part in (telegram_candidate_context_text(related, related_messages, extra_texts), button_text) if part)
                link_contexts.setdefault(link, context_for_115_link(context_source, link, len(link_contexts) + 1))
        return _elapsed_ms(started), button_links

    def _log_link_extraction(self, message: Any, source: str, related_messages: list[Any], link_contexts: dict[str, str], message_text: str, payload: dict[str, int]) -> None:
        if not link_contexts:
            self._log_no_links(message, message_text)
            return
        add_log(
            "debug",
            "telegram",
            "Telegram 消息链接提取完成",
            {
                "message_id": getattr(message, "id", None),
                "source": source,
                "related_messages": len(related_messages),
                "links": len(link_contexts),
                **payload,
            },
        )

    async def _messages_for_link_extraction(self, client: TelegramClient | None, message: Any, entity: Any = None, match_queries: list[str] | None = None, extra_texts: list[str] | None = None) -> list[Any]:
        extra_text_block = "\n".join(extra_texts or [])
        if extra_text_block and extract_115_links(extra_text_block):
            return [message]
        return await self._related_messages_for_link_scan(client, message, entity, match_queries)

    def _combined_message_text(self, messages: list[Any], extra_texts: list[str] | None = None) -> str:
        parts = [text for text in dict.fromkeys(telegram_message_text(item) for item in messages) if text]
        if extra_texts:
            parts.extend(text for text in extra_texts if text)
        return "\n".join(dict.fromkeys(parts))

    def _extract_link_contexts(self, text: str) -> dict[str, str]:
        links = extract_115_links(text)
        return {link: context_for_115_link(text, link, len(links)) for link in links}

    async def _collect_text_external_page_contexts(self, message_text: str, link_contexts: dict[str, str]) -> None:
        # Only fetch third-party resource pages. Skip URLs that already resolved as 115 shares.
        known_links = set(link_contexts) | set(extract_115_links(message_text))
        external_pages = [
            (page_url, "消息外链")
            for page_url in self._external_resource_page_urls(message_text)
            if page_url not in known_links and not extract_115_links(page_url)
        ]
        if not external_pages:
            return

        def collect(value: Any, label: str) -> None:
            context_source = "\n".join(part for part in (message_text, label, str(value or "")) if part)
            for link in extract_115_links(value):
                link_contexts.setdefault(link, context_for_115_link(context_source, link, len(link_contexts) + 1))

        await self._collect_external_page_links(external_pages, collect)

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

    def _log_no_links(self, message: Any, message_text: str) -> None:
        add_log(
            "debug",
            "telegram",
            "Telegram 消息未提取到 115 链接",
            {
                "message_id": getattr(message, "id", None),
                "grouped_id": str(getattr(message, "grouped_id", "") or ""),
                "media": type(getattr(message, "media", None)).__name__ if getattr(message, "media", None) else "",
                "text_length": len(message_text),
                "text_preview": message_text[:500],
                "buttons": self._button_labels(message),
            },
        )

    def _button_labels(self, message: Any) -> list[str]:
        return [getattr(button, "text", "") or "" for row in (getattr(message, "buttons", None) or []) for button in row if getattr(button, "text", "")][:8]


