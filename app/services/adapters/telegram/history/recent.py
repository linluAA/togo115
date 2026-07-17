from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.history.cursor import TelegramCursorMixin
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget
from app.services.adapters.telegram.pipeline import TelegramPipelineStats, TelegramPipelineMixin
from app.services.link import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    local_text_matches_query,
    message_has_link_button_hint,
    nearby_recent_messages_have_button_hint,
    text_has_external_resource_page_hint,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult


RECENT_LINK_WINDOW_FALLBACK_LIMIT = 10


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


from app.services.adapters.telegram.history.recent_windows import TelegramRecentWindowMixin
from app.services.adapters.telegram.history.recent_extract import TelegramRecentExtractMixin


class TelegramRecentScanMixin(TelegramRecentExtractMixin, TelegramRecentWindowMixin, TelegramPipelineMixin, TelegramCursorMixin):
    async def _scan_recent_messages(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        seen_messages: set[int],
        stats: dict[str, int],
        *,
        incremental: bool = False,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        read_started = time.perf_counter()
        recent_messages, max_seen_message_id = await self._read_recent_messages(client, entity, source, options, budget, stats, incremental)
        read_ms = _elapsed_ms(read_started)
        if not recent_messages:
            add_log(
                "warning",
                "telegram",
                "Telegram 最近消息读取为空，已继续尝试服务端搜索",
                {"dialog": source, "limit": options.fallback_scan_limit, "incremental": incremental, "read_ms": read_ms},
            )
        extract_started = time.perf_counter()
        results = await self._extract_recent_message_links(client, entity, source, queries, budget, seen_messages, stats, recent_messages)
        extract_ms = _elapsed_ms(extract_started)
        cursor = self._telegram_cursor(source) if incremental else 0
        add_log(
            "debug",
            "telegram",
            "Telegram 最近消息快速扫描完成",
            {
                "dialog": source,
                "read": len(recent_messages),
                "matched": stats.get("recent_matched", 0),
                "link_windows": stats.get("recent_link_windows", 0),
                "links": len(results),
                "incremental": incremental,
                "cursor": cursor,
                "max_seen": max_seen_message_id,
                "read_ms": read_ms,
                "extract_ms": extract_ms,
                "total_ms": _elapsed_ms(started),
            },
        )
        if incremental and max_seen_message_id > cursor:
            self._update_telegram_cursor(source, max_seen_message_id)
        return results

    async def _read_recent_messages(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        stats: dict[str, int],
        incremental: bool,
    ) -> tuple[list[Any], int]:
        recent_messages: list[Any] = []
        timeout = budget.timeout(options.recent_budget)
        cursor = self._telegram_cursor(source) if incremental else 0
        max_seen_message_id = cursor
        add_log(
            "debug",
            "telegram",
            "Telegram 最近消息快速扫描开始",
            {"dialog": source, "limit": options.fallback_scan_limit, "timeout": round(timeout, 2), "incremental": incremental, "cursor": cursor},
        )
        try:
            async with asyncio.timeout(timeout):
                messages = await self._get_recent_messages(client, entity, options.fallback_scan_limit)
                for message in messages:
                    message_id = int(getattr(message, "id", 0) or 0)
                    if message_id:
                        if incremental and cursor and message_id <= cursor:
                            break
                        max_seen_message_id = max(max_seen_message_id, message_id)
                    recent_messages.append(message)
        except asyncio.TimeoutError:
            stats["timeouts"] += 1
            add_log("warning", "telegram", "Telegram 最近消息兜底扫描超时", {"dialog": source, "read": len(recent_messages), "timeout": round(timeout, 2)})
        except Exception as exc:
            add_log("warning", "telegram", "Telegram 最近消息兜底扫描失败", {"dialog": source, "error": str(exc), "error_type": type(exc).__name__})
        if recent_messages:
            self._index_telegram_messages(source, recent_messages)
        return recent_messages, max_seen_message_id

    async def _get_recent_messages(self, client: TelegramClient, entity: Any, limit: int) -> list[Any]:
        get_messages = getattr(client, "get_messages", None)
        if callable(get_messages):
            try:
                messages = await asyncio.wait_for(get_messages(entity, limit=limit), timeout=2)
                items = messages if isinstance(messages, list) else list(messages or [])
                if items:
                    return items
                add_log("debug", "telegram", "Telegram get_messages 最近消息为空，回退 iter_messages", {"limit": limit})
            except asyncio.TimeoutError:
                add_log("debug", "telegram", "Telegram get_messages 最近消息超时，回退 iter_messages", {"limit": limit, "timeout": 2})
            except Exception as exc:
                add_log("debug", "telegram", "Telegram get_messages 最近消息失败，回退 iter_messages", {"limit": limit, "error": str(exc), "error_type": type(exc).__name__})
        try:
            messages = await asyncio.wait_for(self._iter_recent_messages(client, entity, limit), timeout=4)
            if messages:
                add_log("debug", "telegram", "Telegram iter_messages 最近消息读取成功", {"limit": limit, "count": len(messages)})
            return messages
        except asyncio.TimeoutError:
            add_log("warning", "telegram", "Telegram iter_messages 最近消息读取超时", {"limit": limit, "timeout": 4})
        except Exception as exc:
            add_log("warning", "telegram", "Telegram iter_messages 最近消息读取失败", {"limit": limit, "error": str(exc), "error_type": type(exc).__name__})
        return []

    async def _iter_recent_messages(self, client: TelegramClient, entity: Any, limit: int) -> list[Any]:
        messages: list[Any] = []
        async for message in client.iter_messages(entity, limit=limit, wait_time=0):
            messages.append(message)
        return messages

