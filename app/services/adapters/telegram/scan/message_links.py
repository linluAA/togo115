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
from app.services.link_parser import (
    context_for_115_link,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult


TITLE_LABEL_RE = re.compile(
    r"(?:^|[\s\[\u3010\uff08(])(?:\u7535\u89c6\u5267|\u7535\u5f71|\u52a8\u6f2b|\u52a8\u753b|\u7efc\u827a|\u5267\u96c6|\u77ed\u5267|\u756a\u5267|\u540d\u79f0|\u7247\u540d|\u5267\u540d|\u6807\u9898|\u8d44\u6e90\u540d|\u8d44\u6e90)\s*[:\uff1a\uff5c|]\s*",
    re.I,
)
TITLE_SKIP_RE = re.compile(r"(?:\u6807\u7b7e|\u7b80\u4ecb|\u4e3b\u6f14|\u8bc4\u5206|\u7c7b\u578b|\u5206\u7c7b|\u5927\u5c0f|\u8d28\u91cf|\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u94fe\u63a5|TMDB\s*ID)", re.I)
TITLE_CLEAN_RE = re.compile(
    r"^(?:[\s\[\u3010\uff08(])*(?:\u7535\u89c6\u5267|\u7535\u5f71|\u52a8\u6f2b|\u52a8\u753b|\u7efc\u827a|\u5267\u96c6|\u77ed\u5267|\u756a\u5267|\u540d\u79f0|\u7247\u540d|\u5267\u540d|\u6807\u9898|\u8d44\u6e90\u540d|\u8d44\u6e90)\s*[:\uff1a\uff5c|]\s*",
    re.I,
)
NON_TITLE_RE = re.compile(r"(?:\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u5bc6\u7801|\u590d\u5236|\u4e0b\u8f7d|\u94fe\u63a5|\u6587\u4ef6\u5927\u5c0f|\u6587\u4ef6\u6570\u91cf|\u6536\u5f55\u65f6\u95f4|\u5206\u4eab\u65f6\u95f4)", re.I)
EPISODE_QUALITY_RE = re.compile(r"(?i)(S\d{1,2}E\d{1,3}|\u7b2c\s*\d{1,3}\s*[\u96c6\u8bdd\u8a71]|1080p|2160p|4K|BluRay|WEB)")
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


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
        related_messages, related_ms = await self._timed_related_messages(client, message, entity, match_queries, extra_texts)
        message_text = self._combined_message_text(related_messages, extra_texts)
        link_contexts, direct_ms, direct_links = self._timed_direct_link_contexts(related_messages, extra_texts)
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
        })
        return self._search_results_from_contexts(message, source, link_contexts)

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


def _telegram_resource_title(context: str | None) -> str:
    lines = [line.strip() for line in str(context or "").splitlines() if line.strip()]
    labeled = [_strip_title_label(line) for line in lines if _title_label_score(line) > 0]
    for title in labeled:
        if _usable_title_line(title):
            return title[:120]
    scored = _scored_title_lines(lines)
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]
    return "Telegram 资源"


def _scored_title_lines(lines: list[str]) -> list[tuple[int, str]]:
    scored: list[tuple[int, str]] = []
    for line in lines:
        title = _strip_title_label(line)
        if not _usable_title_line(title):
            continue
        score = 1
        if YEAR_RE.search(title):
            score += 4
        if EPISODE_QUALITY_RE.search(title):
            score += 2
        if 4 <= len(title) <= 80:
            score += 1
        scored.append((score, title[:120]))
    return scored


def _title_label_score(line: str) -> int:
    value = str(line or "").strip()
    if not value or TITLE_SKIP_RE.search(value):
        return 0
    if not TITLE_LABEL_RE.search(value):
        return 0
    return 2 if YEAR_RE.search(value) else 1


def _strip_title_label(line: str) -> str:
    value = str(line or "").strip()
    value = TITLE_CLEAN_RE.sub("", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"(?:链接|地址|提取码|访问码|密码)\s*[:：].*$", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" -_·|")


def _usable_title_line(line: str) -> bool:
    value = str(line or "").strip()
    if len(value) < 2:
        return False
    if "115.com/s/" in value or "115cdn.com/s/" in value or value.casefold().startswith("magnet:?"):
        return False
    if NON_TITLE_RE.search(value):
        return False
    return bool(re.search(r"[\u3400-\u9fffA-Za-z0-9]", value))
