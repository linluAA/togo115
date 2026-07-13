from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram_cursor import _TelegramCursorMixin
from app.services.adapters.telegram_models import _TelegramHistoryOptions, _TelegramSearchBudget
from app.services.adapters.telegram_pipeline import TelegramPipelineStats, _TelegramPipelineMixin
from app.services.link_parser import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    _local_text_matches_query,
    _message_has_link_button_hint,
    _nearby_recent_messages_have_button_hint,
    _text_has_external_resource_page_hint,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult


RECENT_LINK_WINDOW_FALLBACK_LIMIT = 10


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class _TelegramRecentScanMixin(_TelegramPipelineMixin, _TelegramCursorMixin):
    async def _scan_recent_messages(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        options: _TelegramHistoryOptions,
        budget: _TelegramSearchBudget,
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
        options: _TelegramHistoryOptions,
        budget: _TelegramSearchBudget,
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

    async def _extract_recent_message_links(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        budget: _TelegramSearchBudget,
        seen_messages: set[int],
        stats: dict[str, int],
        recent_messages: list[Any],
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        pipeline_stats = TelegramPipelineStats(read=len(recent_messages), timeouts=stats.get("timeouts", 0))
        title_started = time.perf_counter()
        results.extend(
            await self._extract_recent_title_windows(
                client,
                entity,
                source,
                queries,
                budget,
                seen_messages,
                stats,
                recent_messages,
                pipeline_stats,
            )
        )
        pipeline_stats.bump("title_window_ms", _elapsed_ms(title_started))
        if not results and not budget.exhausted():
            link_started = time.perf_counter()
            fallback_results, fallback_windows = await self._extract_recent_link_windows(
                client,
                entity,
                source,
                budget,
                seen_messages,
                recent_messages,
                pipeline_stats,
            )
            results.extend(fallback_results)
            pipeline_stats.link_windows += fallback_windows
            pipeline_stats.bump("link_window_ms", _elapsed_ms(link_started))
        self._update_recent_scan_stats(stats, pipeline_stats)
        return results

    async def _extract_recent_title_windows(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        budget: _TelegramSearchBudget,
        seen_messages: set[int],
        stats: dict[str, int],
        recent_messages: list[Any],
        pipeline_stats: TelegramPipelineStats,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index, message in enumerate(recent_messages):
            if budget.exhausted() or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                break
            if index and index % 25 == 0:
                await asyncio.sleep(0)
            hits = await self._extract_recent_title_window(
                client,
                entity,
                source,
                queries,
                seen_messages,
                stats,
                pipeline_stats,
                recent_messages,
                index,
            )
            results.extend(hits)
        return results

    async def _extract_recent_title_window(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        seen_messages: set[int],
        stats: dict[str, int],
        pipeline_stats: TelegramPipelineStats,
        recent_messages: list[Any],
        index: int,
    ) -> list[SearchResult]:
        message = recent_messages[index]
        window_messages = self._recent_window_messages(recent_messages, index)
        window_texts = self._recent_window_texts(window_messages, message)
        matched_queries = self._matched_recent_queries_in_text("\n".join([telegram_message_text(message), *window_texts]), queries)
        if not matched_queries:
            return []
        pipeline_stats.title_matched += 1
        anchor = self._recent_link_anchor(message, window_messages, window_texts)
        if not anchor:
            pipeline_stats.skipped_no_link_hint += 1
            return []
        pipeline_stats.link_windows += 1
        stats["fallback"] += 1
        return await self._pipeline_extract_message_links(
            client,
            entity,
            source,
            anchor,
            matched_queries,
            window_texts,
            seen_messages,
            pipeline_stats,
            stage="recent_title_window",
        )

    def _update_recent_scan_stats(self, stats: dict[str, int], pipeline_stats: TelegramPipelineStats) -> None:
        stats["recent_matched"] = pipeline_stats.title_matched
        stats["recent_link_windows"] = pipeline_stats.link_windows
        stats["skipped_no_link_hint"] = pipeline_stats.skipped_no_link_hint
        stats["pipeline_extracted_links"] = pipeline_stats.extracted_links
        stats["pipeline_no_link"] = pipeline_stats.no_link
        stats["pipeline_duplicate_messages"] = pipeline_stats.duplicate_messages
        for key, value in pipeline_stats.extra.items():
            stats[f"pipeline_{key}"] = value

    async def _extract_recent_link_windows(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        budget: _TelegramSearchBudget,
        seen_messages: set[int],
        recent_messages: list[Any],
        pipeline_stats: TelegramPipelineStats | None = None,
    ) -> tuple[list[SearchResult], int]:
        results: list[SearchResult] = []
        link_windows = 0
        active_stats = pipeline_stats or TelegramPipelineStats(read=len(recent_messages))
        for index, message in enumerate(recent_messages):
            if budget.exhausted() or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                break
            if link_windows >= RECENT_LINK_WINDOW_FALLBACK_LIMIT:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 最近消息链接窗口兜底已达到上限，提前停止",
                    {"dialog": source, "limit": RECENT_LINK_WINDOW_FALLBACK_LIMIT, "read": len(recent_messages), "links": len(results)},
                )
                break
            if index and index % 25 == 0:
                await asyncio.sleep(0)
            window_messages = self._recent_window_messages(recent_messages, index)
            window_texts = self._recent_window_texts(window_messages, message)
            anchor = self._recent_link_anchor(message, window_messages, window_texts)
            if not anchor:
                continue
            link_windows += 1
            hits = await self._pipeline_extract_message_links(
                client,
                entity,
                source,
                anchor,
                [],
                window_texts,
                seen_messages,
                active_stats,
                stage="recent_link_window_fallback",
            )
            results.extend(hits)
        if link_windows:
            add_log(
                "info",
                "telegram",
                "Telegram 最近消息未命中标题，已回退提取链接窗口供订阅条件过滤",
                {"dialog": source, "link_windows": link_windows, "links": len(results)},
            )
        return results, link_windows

    def _matched_recent_queries(self, message: Any, queries: list[str]) -> list[str]:
        return self._matched_recent_queries_in_text(telegram_message_text(message), queries)

    def _matched_recent_queries_in_text(self, text: str, queries: list[str]) -> list[str]:
        return [query for query in queries if _local_text_matches_query(text, query)]

    def _recent_window_messages(self, messages: list[Any], index: int, window: int = 4) -> list[Any]:
        return [messages[item_index] for item_index in range(max(0, index - window), min(len(messages), index + window + 1)) if item_index != index]

    def _recent_window_texts(self, window_messages: list[Any], base_message: Any) -> list[str]:
        texts: list[str] = []
        seen: set[str] = {telegram_message_text(base_message)}
        for item in window_messages:
            text = telegram_message_text(item)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return texts

    def _recent_link_anchor(self, message: Any, window_messages: list[Any], window_texts: list[str]) -> Any | None:
        if self._message_has_link_hint(message):
            return message
        for item in window_messages:
            if self._message_has_link_hint(item):
                return item
        return message if any(extract_115_links(text) or _text_has_external_resource_page_hint(text) for text in window_texts) else None

    def _recent_message_has_link_hint(self, message: Any, nearby_texts: list[str], recent_messages: list[Any], index: int) -> bool:
        text = telegram_message_text(message)
        return bool(
            extract_115_links(text)
            or any(extract_115_links(item) for item in nearby_texts)
            or _text_has_external_resource_page_hint(text)
            or any(_text_has_external_resource_page_hint(item) for item in nearby_texts)
            or _message_has_link_button_hint(message)
            or _nearby_recent_messages_have_button_hint(recent_messages, index)
        )

    def _message_has_link_hint(self, message: Any) -> bool:
        text = telegram_message_text(message)
        return bool(extract_115_links(text) or _text_has_external_resource_page_hint(text) or _message_has_link_button_hint(message))
