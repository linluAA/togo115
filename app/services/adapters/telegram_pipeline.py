from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.link_parser import telegram_message_text
from app.services.types import SearchResult


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


@dataclass
class TelegramPipelineStats:
    read: int = 0
    title_matched: int = 0
    link_windows: int = 0
    extracted_links: int = 0
    no_link: int = 0
    duplicate_messages: int = 0
    skipped_no_link_hint: int = 0
    timeouts: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, amount: int = 1) -> None:
        if hasattr(self, key):
            setattr(self, key, int(getattr(self, key)) + amount)
            return
        self.extra[key] = self.extra.get(key, 0) + amount

    def as_payload(self) -> dict[str, int]:
        return {
            "read": self.read,
            "title_matched": self.title_matched,
            "link_windows": self.link_windows,
            "extracted_links": self.extracted_links,
            "no_link": self.no_link,
            "duplicate_messages": self.duplicate_messages,
            "skipped_no_link_hint": self.skipped_no_link_hint,
            "timeouts": self.timeouts,
            **self.extra,
        }


class _TelegramPipelineMixin:
    def _pipeline_message_id(self, message: Any) -> int:
        return int(getattr(message, "id", 0) or 0)

    def _pipeline_seen_or_mark(self, message: Any, seen_messages: set[int], stats: TelegramPipelineStats) -> bool:
        message_id = self._pipeline_message_id(message)
        if message_id and message_id in seen_messages:
            stats.duplicate_messages += 1
            return True
        if message_id:
            seen_messages.add(message_id)
        return False

    async def _pipeline_extract_message_links(
        self,
        client: TelegramClient | None,
        entity: Any,
        source: str,
        message: Any,
        match_queries: list[str],
        extra_texts: list[str] | None,
        seen_messages: set[int],
        stats: TelegramPipelineStats,
        *,
        stage: str,
    ) -> list[SearchResult]:
        if self._pipeline_seen_or_mark(message, seen_messages, stats):
            return []
        started = time.perf_counter()
        hits = await self._links_from_message(client, message, source, entity, match_queries, extra_texts)
        stats.bump(f"{stage}_extract_ms", _elapsed_ms(started))
        if hits:
            stats.extracted_links += len(hits)
        else:
            stats.no_link += 1
            if stage != "recent_link_window_fallback" or stats.no_link <= 3:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 流水线命中消息但未提取到链接",
                    {
                        "stage": stage,
                        "dialog": source,
                        "message_id": self._pipeline_message_id(message),
                        "queries": match_queries[:3],
                        "text_preview": "\n".join([telegram_message_text(message), *(extra_texts or [])])[:500],
                    },
                )
        return hits
