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


def _recent_message_id(message: Any) -> int:
    try:
        return int(getattr(message, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


# Non-incremental recent scans index a contiguous window from the newest message;
# the watermark records that window's top so later scans only read messages that
# are actually newer (previously indexed rows are skipped).
RECENT_WATERMARK_TTL_SECONDS = 600
_RECENT_WATERMARKS: dict[str, tuple[float, int]] = {}


def _recent_watermark_get(source: str) -> int:
    key = str(source or "").strip()
    if not key:
        return 0
    item = _RECENT_WATERMARKS.get(key)
    if item is None:
        return 0
    stamp, message_id = item
    if time.monotonic() - stamp > RECENT_WATERMARK_TTL_SECONDS:
        _RECENT_WATERMARKS.pop(key, None)
        return 0
    return int(message_id or 0)


def _recent_watermark_set(source: str, message_id: int) -> None:
    key = str(source or "").strip()
    value = int(message_id or 0)
    if not key or value <= 0:
        return
    _RECENT_WATERMARKS[key] = (time.monotonic(), value)
    if len(_RECENT_WATERMARKS) > 512:
        # Linear scan for expired entries (TTL check) — O(n) instead of O(n log n) sort.
        now = time.monotonic()
        expired = [k for k, (stamp, _) in _RECENT_WATERMARKS.items() if now - stamp > RECENT_WATERMARK_TTL_SECONDS]
        if expired:
            for k in expired:
                _RECENT_WATERMARKS.pop(k, None)
        # If still over limit after TTL eviction, remove oldest 20% via linear scan.
        if len(_RECENT_WATERMARKS) > 512:
            # Find threshold: the timestamp at 20% position.
            entries = list(_RECENT_WATERMARKS.items())
            cutoff_idx = int(len(entries) * 0.2)
            # Sort only the first cutoff_idx+1 entries to find the cutoff timestamp.
            # Use nsmallest for O(n log k) where k = cutoff_idx << n.
            import heapq
            oldest_k = heapq.nsmallest(cutoff_idx + 1, entries, key=lambda item: item[1][0])
            if oldest_k:
                threshold = oldest_k[-1][1][0]
                for k, (stamp, _) in entries:
                    if stamp <= threshold:
                        _RECENT_WATERMARKS.pop(k, None)
                    if len(_RECENT_WATERMARKS) <= 512:
                        break


def clear_recent_watermarks(source: str | None = None) -> None:
    if source is None:
        _RECENT_WATERMARKS.clear()
        return
    key = str(source or "").strip()
    if key:
        _RECENT_WATERMARKS.pop(key, None)


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
            skipped_existing = not incremental and _recent_watermark_get(source) > 0
            add_log(
                "debug" if skipped_existing else "warning",
                "telegram",
                "Telegram 最近消息无新增" if skipped_existing else "Telegram 最近消息读取为空，已继续尝试服务端搜索",
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
        safe_ids = stats.get("_recent_safe_ids")
        safe_max_message_id = cursor
        if isinstance(safe_ids, set):
            for message_id in sorted({_recent_message_id(message) for message in recent_messages}, reverse=True):
                if message_id <= 0:
                    continue
                if message_id <= cursor:
                    break
                if message_id not in safe_ids:
                    break
                safe_max_message_id = message_id
        if incremental and safe_max_message_id > cursor:
            self._update_telegram_cursor(source, safe_max_message_id)
        stats.pop("_recent_safe_ids", None)
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
        watermark = 0 if incremental else _recent_watermark_get(source)
        max_seen_message_id = cursor
        add_log(
            "debug",
            "telegram",
            "Telegram 最近消息快速扫描开始",
            {"dialog": source, "limit": options.fallback_scan_limit, "timeout": round(timeout, 2), "incremental": incremental, "cursor": cursor},
        )
        completed = True
        try:
            async with asyncio.timeout(timeout):
                messages = await self._get_recent_messages(client, entity, options.fallback_scan_limit)
                for message in messages:
                    message_id = _recent_message_id(message)
                    if message_id:
                        if incremental and cursor and message_id <= cursor:
                            break
                        if not incremental and watermark and message_id <= watermark:
                            break
                        max_seen_message_id = max(max_seen_message_id, message_id)
                    recent_messages.append(message)
        except asyncio.TimeoutError:
            completed = False
            stats["timeouts"] += 1
            add_log("warning", "telegram", "Telegram 最近消息兜底扫描超时", {"dialog": source, "read": len(recent_messages), "timeout": round(timeout, 2)})
        except Exception as exc:
            completed = False
            add_log("warning", "telegram", "Telegram 最近消息兜底扫描失败", {"dialog": source, "error": str(exc), "error_type": type(exc).__name__})
        if not incremental and completed and max_seen_message_id > 0:
            _recent_watermark_set(source, max_seen_message_id)
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
        # iter_messages fallback: shorter timeout so the total chain stays within
        # the 12s recent_budget / 4s single-query budget.
        try:
            messages = await asyncio.wait_for(self._iter_recent_messages(client, entity, limit), timeout=3)
            if messages:
                add_log("debug", "telegram", "Telegram iter_messages 最近消息读取成功", {"limit": limit, "count": len(messages)})
            return messages
        except asyncio.TimeoutError:
            add_log("warning", "telegram", "Telegram iter_messages 最近消息读取超时", {"limit": limit, "timeout": 3})
        except Exception as exc:
            add_log("warning", "telegram", "Telegram iter_messages 最近消息读取失败", {"limit": limit, "error": str(exc), "error_type": type(exc).__name__})
        return []

    async def _iter_recent_messages(self, client: TelegramClient, entity: Any, limit: int) -> list[Any]:
        messages: list[Any] = []
        # Small wait_time to avoid triggering Telegram FloodWait on rapid pagination.
        async for message in client.iter_messages(entity, limit=limit, wait_time=0.05):
            messages.append(message)
        return messages

