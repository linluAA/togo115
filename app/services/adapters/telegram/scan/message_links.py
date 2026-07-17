from __future__ import annotations

import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.scan.extract_cache import get_cached_message_extract
from app.services.adapters.telegram.scan.message_links_extract import TelegramMessageLinkExtractMixin, _elapsed_ms
from app.services.adapters.telegram.scan.message_links_filter import TelegramMessageLinkFilterMixin
from app.services.types import SearchResult


class TelegramMessageLinkMixin(TelegramMessageLinkFilterMixin, TelegramMessageLinkExtractMixin):
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

from app.services.adapters.telegram.scan.message_titles import _telegram_resource_title  # noqa: F401,E402
