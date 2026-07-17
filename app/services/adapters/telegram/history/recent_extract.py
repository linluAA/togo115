from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    local_text_matches_query,
    message_has_link_button_hint,
    nearby_recent_messages_have_button_hint,
    text_has_external_resource_page_hint,
    telegram_message_text,
)
from app.services.types import SearchResult


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramRecentExtractMixin:
    async def _extract_recent_message_links(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        queries: list[str],
        budget: TelegramSearchBudget,
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
        budget: TelegramSearchBudget,
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
        base_text = telegram_message_text(message)
        matched_queries = self._matched_recent_queries_in_text("\n".join([base_text, *window_texts]), queries)
        if not matched_queries:
            return []
        pipeline_stats.title_matched += 1
        anchor = self._recent_link_anchor(message, window_messages, window_texts)
        if not anchor:
            pipeline_stats.skipped_no_link_hint += 1
            return []
        pipeline_stats.link_windows += 1
        stats["fallback"] += 1
        # Keep the matched title text even when the extract anchor is a nearby
        # link-only message; otherwise query filters drop the share.
        extra_texts = self._recent_extract_extra_texts(message, anchor, window_texts)
        return await self._pipeline_extract_message_links(
            client,
            entity,
            source,
            anchor,
            matched_queries,
            extra_texts,
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
        budget: TelegramSearchBudget,
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
            extra_texts = self._recent_extract_extra_texts(message, anchor, window_texts)
            hits = await self._pipeline_extract_message_links(
                client,
                entity,
                source,
                anchor,
                [],
                extra_texts,
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

    def _recent_extract_extra_texts(self, message: Any, anchor: Any, window_texts: list[str]) -> list[str]:
        """Preserve title text when extraction anchors on a nearby link-only message."""
        texts: list[str] = []
        seen: set[str] = set()
        for value in (telegram_message_text(message), telegram_message_text(anchor), *window_texts):
            item = str(value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            texts.append(item)
        return texts

