from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.history.query_result_cache import (
    get_cached_query_results,
    set_cached_query_results,
)
from app.services.link import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    local_text_matches_query,
    message_has_link_button_hint,
    telegram_message_text,
    text_has_external_resource_page_hint,
)
from app.services.adapters.telegram.models import (
    TelegramHistoryOptions,
    TelegramSearchBudget,
    TelegramSearchSharedState,
)
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.types import SearchResult


BODY_ONLY_PARALLEL = 3
DEEP_EXTRACT_MESSAGE_LIMIT = 8
BUTTON_DEEP_EXTRACT_LIMIT = 8
EXTERNAL_PAGE_DEEP_EXTRACT_LIMIT = 8


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _cached_results_matching_query(results: list[SearchResult], query: str) -> list[SearchResult]:
    accepted: list[SearchResult] = []
    for result in results:
        context = str(getattr(result, "context", "") or getattr(result, "title", "") or "")
        if not local_text_matches_query(context, query):
            continue
        title = str(getattr(result, "title", "") or "")
        if title and not title.startswith("Telegram ") and not local_text_matches_query(title, query):
            continue
        accepted.append(result)
    return accepted


class TelegramDialogQueryExecutorMixin:
    async def _search_dialog_query(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        query: str,
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        seen_messages: set[int],
        stats: dict[str, int],
        *,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        results: list[SearchResult] = []
        processed = 0
        pipeline_stats = TelegramPipelineStats()
        timeout = budget.timeout(options.query_budget)
        read_ms = 0
        extract_ms = 0
        state = shared_state
        if state is not None:
            cached = state.get_cached_query_dialog_results(source, query)
            if cached is not None:
                accepted = _cached_results_matching_query(cached, query)
                if accepted:
                    stats["cache_hits"] = int(stats.get("cache_hits", 0) or 0) + 1
                    return accepted
        process_cached = get_cached_query_results(source, query)
        if process_cached is not None:
            accepted = _cached_results_matching_query(process_cached, query)
            if accepted:
                stats["cache_hits"] = int(stats.get("cache_hits", 0) or 0) + 1
                if state is not None:
                    state.set_cached_query_dialog_results(source, query, accepted)
                return accepted
        try:
            async with asyncio.timeout(timeout):
                read_started = time.perf_counter()
                messages = await self._get_search_messages(client, entity, query, options)
                self._index_telegram_messages(source, messages)
                read_ms = _elapsed_ms(read_started)
                pipeline_stats.read = len(messages)
                extract_started = time.perf_counter()
                # Keep scanning after an early direct hit: later ranked messages
                # often carry the actual external page or button link.
                deep_budget = min(len(messages), max(2, min(DEEP_EXTRACT_MESSAGE_LIMIT, int(options.messages_per_query or 4))))
                button_deep_budget = min(len(messages), max(deep_budget, min(12, int(options.messages_per_query or 12))))
                button_deep_count = 0
                external_page_deep_count = 0
                body_batch: list[Any] = []

                async def flush_body_batch() -> None:
                    nonlocal results
                    if not body_batch:
                        return
                    chunk = list(body_batch)
                    body_batch.clear()
                    # Concurrent body-only extract with isolated seen sets, then merge in order.
                    gathered = await asyncio.gather(
                        *[
                            self._body_only_extract_message_links(
                                source,
                                message,
                                query,
                                set(),
                                TelegramPipelineStats(),
                            )
                            for message in chunk
                        ]
                    )
                    for message, links in zip(chunk, gathered):
                        try:
                            mid = int(getattr(message, "id", 0) or 0)
                        except (TypeError, ValueError):
                            mid = 0
                        if mid and mid in seen_messages:
                            pipeline_stats.duplicate_messages += 1
                            continue
                        if not links:
                            pipeline_stats.no_link += 1
                            continue
                        if mid:
                            seen_messages.add(mid)
                        pipeline_stats.extracted_links += len(links)
                        results.extend(links)

                for index, message in enumerate(messages):
                    processed += 1
                    stats["searched"] += 1
                    pipeline_stats.title_matched += 1
                    suggests = self._message_suggests_resource_links(message)
                    button_hint = message_has_link_button_hint(message)
                    external_page_hint = text_has_external_resource_page_hint(telegram_message_text(message))
                    if button_hint:
                        button_deep_count += 1
                    if external_page_hint:
                        external_page_deep_count += 1
                    should_deep_extract = suggests and (
                        index < deep_budget
                        or (button_hint and button_deep_count <= BUTTON_DEEP_EXTRACT_LIMIT and index < button_deep_budget)
                        or (external_page_hint and external_page_deep_count <= EXTERNAL_PAGE_DEEP_EXTRACT_LIMIT)
                    )
                    if should_deep_extract:
                        await flush_body_batch()
                        links = await self._pipeline_extract_message_links(
                            client,
                            entity,
                            source,
                            message,
                            [query],
                            None,
                            seen_messages,
                            pipeline_stats,
                            stage="server_search",
                        )
                        results.extend(links)
                    else:
                        body_batch.append(message)
                        if len(body_batch) >= BODY_ONLY_PARALLEL:
                            await flush_body_batch()
                    if processed >= options.messages_per_query or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                        break
                await flush_body_batch()
                extract_ms = _elapsed_ms(extract_started)
        except asyncio.TimeoutError:
            stats["timeouts"] += 1
            add_log("warning", "telegram", "Telegram 单次查询超时，继续下一个查询", {"dialog": source, "query": query, "timeout": round(timeout, 2), "messages": processed, "read_ms": read_ms, "extract_ms": extract_ms})
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("warning", "telegram", "Telegram 历史查询失败", {"dialog": source, "query": query, "error": str(exc), "error_type": type(exc).__name__})
        payload = {"dialog": source, "query": query, "messages": processed, "read_ms": read_ms, "extract_ms": extract_ms, "total_ms": _elapsed_ms(started), **pipeline_stats.as_payload()}
        if processed and not results:
            add_log("debug", "telegram", "Telegram 查询匹配到消息但未提取到链接", payload)
        elif not processed:
            add_log("debug", "telegram", "Telegram 查询未匹配到消息", payload)
        stats["pipeline_extracted_links"] = stats.get("pipeline_extracted_links", 0) + pipeline_stats.extracted_links
        stats["pipeline_no_link"] = stats.get("pipeline_no_link", 0) + pipeline_stats.no_link
        stats["pipeline_duplicate_messages"] = stats.get("pipeline_duplicate_messages", 0) + pipeline_stats.duplicate_messages
        stats["pipeline_skipped_no_link_hint"] = stats.get("pipeline_skipped_no_link_hint", 0) + pipeline_stats.skipped_no_link_hint
        if state is not None:
            state.set_cached_query_dialog_results(source, query, results)
        set_cached_query_results(source, query, results)
        return results
