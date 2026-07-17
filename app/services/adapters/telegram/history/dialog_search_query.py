from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.link import TELEGRAM_HISTORY_MAX_RESULTS
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.adapters.telegram.scan.extract_cache import extract_cache_stats
from app.services.types import SearchResult


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramDialogSearchQueryMixin:
    async def _search_dialog_history(
        self,
        client: TelegramClient,
        dialog: dict[str, Any],
        queries: list[str],
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        *,
        incremental: bool = False,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> tuple[list[SearchResult], int]:
        started = time.perf_counter()
        entity = dialog["entity"]
        source = str(dialog["canonical"])
        results: list[SearchResult] = []
        state = shared_state or TelegramSearchSharedState()
        seen_messages = state.seen_messages_for(source)
        stats = {"searched": 0, "fallback": 0, "links": 0, "timeouts": 0, "skipped_no_link_hint": 0}
        add_log("debug", "telegram", "Telegram 来源搜索开始", {"dialog": source, "queries": queries, "recent_limit": options.fallback_scan_limit, "server_limit": options.history_limit})

        recent_ms = 0
        server_ms = 0
        # Non-incremental: prefer server search first. Recent scan is only a fallback.
        if not incremental and not budget.exhausted():
            server_started = time.perf_counter()
            for query in self._server_search_queries(queries):
                if budget.exhausted() or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                    break
                hits = await self._search_dialog_query(client, entity, source, query, options, budget, seen_messages, stats)
                results.extend(hits)
            server_ms = _elapsed_ms(server_started)
            if results:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 服务端搜索已命中，跳过最近消息兜底扫描",
                    {"dialog": source, "links": len(results), "server_ms": server_ms},
                )

        if not results and not budget.exhausted():
            recent_started = time.perf_counter()
            recent_hits = await self._scan_recent_messages(
                client,
                entity,
                source,
                queries,
                options,
                budget,
                seen_messages,
                stats,
                incremental=incremental,
            )
            recent_ms = _elapsed_ms(recent_started)
            results.extend(recent_hits)
            if results and not incremental:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 最近消息兜底扫描命中",
                    {"dialog": source, "links": len(results), "recent_ms": recent_ms},
                )

                stats["links"] = len(results)
        total_ms = _elapsed_ms(started)
        # Approximate extract cost as total minus network-ish recent/server stages.
        extract_ms = max(0, total_ms - int(recent_ms or 0) - int(server_ms or 0))
        add_log(
            "debug",
            "telegram",
            "Telegram 来源搜索完成",
            {"dialog": source, **stats, "recent_ms": recent_ms, "server_ms": server_ms, "extract_ms": extract_ms, "total_ms": total_ms, "remaining_budget": round(budget.remaining, 2)},
        )
        return results, extract_ms

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
    ) -> list[SearchResult]:
        started = time.perf_counter()
        results: list[SearchResult] = []
        processed = 0
        pipeline_stats = TelegramPipelineStats()
        timeout = budget.timeout(options.query_budget)
        read_ms = 0
        extract_ms = 0
        try:
            async with asyncio.timeout(timeout):
                read_started = time.perf_counter()
                messages = await self._get_search_messages(client, entity, query, options)
                self._index_telegram_messages(source, messages)
                read_ms = _elapsed_ms(read_started)
                pipeline_stats.read = len(messages)
                extract_started = time.perf_counter()
                for message in messages:
                    processed += 1
                    stats["searched"] += 1
                    pipeline_stats.title_matched += 1
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
                    if processed >= options.messages_per_query or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                        break
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
        return results
