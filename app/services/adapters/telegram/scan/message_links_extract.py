from __future__ import annotations

import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.scan.message_candidates import (
    telegram_candidate_context_text,
    telegram_candidate_link_contexts,
)
from app.services.link import context_for_115_link, extract_115_links, telegram_message_text
from app.services.types import SearchResult


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramMessageLinkExtractMixin:
    async def _message_text_for_link_scan(self, client: TelegramClient | None, message: Any, entity: Any = None, match_queries: list[str] | None = None) -> str:
        texts: list[str] = []
        seen: set[str] = set()
        for related in await self._related_messages_for_link_scan(client, message, entity, match_queries):
            text = telegram_message_text(related)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return "\n".join(texts)

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
