from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services import concurrency as runtime
from app.services.adapters.telegram.history.config import build_history_options, server_search_queries
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.history.metrics import TelegramSearchMetrics
from app.services.adapters.telegram.scan.extract_cache import extract_cache_stats
from app.services.search_metrics import record_telegram_search
from app.services.adapters.telegram.history.dialog_search import TELEGRAM_DIALOG_SEARCH_CONCURRENCY, TelegramDialogSearchMixin
from app.services.adapters.telegram.history.fast import TelegramFastSearchMixin
from app.services.adapters.telegram.history.prewarm import TelegramIndexPrewarmMixin
from app.services.adapters.telegram.scan.message_index import index_telegram_messages, search_telegram_message_index
from app.services.adapters.telegram.history.recent import TelegramRecentScanMixin
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    expanded_search_queries as _expanded_search_queries,
)
from app.services.types import SearchResult
from app.services.adapters.telegram.rate_limit import telegram_request_gate


TELEGRAM_DIALOG_SEARCH_CONCURRENCY = 3
TELEGRAM_HISTORY_RETURN_TARGET = 2


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramHistorySearchMixin(TelegramDialogSearchMixin, TelegramFastSearchMixin, TelegramRecentScanMixin, TelegramIndexPrewarmMixin):
    def _history_options(self, config: dict[str, Any]) -> TelegramHistoryOptions:
        return build_history_options(config)

    def _server_search_queries(self, queries: list[str]) -> list[str]:
        # Keep a small multi-query set so franchise aliases (e.g. 新攻壳机动队 -> 攻壳机动队)
        # can hit traditional titles without exploding Telegram request volume.
        return server_search_queries(queries, limit=2)

    async def search_history(
        self,
        title: str,
        keywords: list[str],
        *,
        incremental: bool = False,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        total_started = time.perf_counter()
        state = shared_state or TelegramSearchSharedState()
        client = await self._authorized_client_for_search()
        if client is None:
            return []
        config = self._config()
        source_values = self._configured_sources(config)
        if not source_values:
            add_log("warning", "telegram", "未配置 Telegram 群组/频道 sources")
            return []

        resolve_started = time.perf_counter()
        dialogs = await self._resolve_dialogs_for_history_search(client, source_values, state)
        resolve_ms = _elapsed_ms(resolve_started)
        if not dialogs:
            add_log("warning", "telegram", "Telegram 群组/频道解析失败或无可用来源", {"sources": len(source_values), "resolve_ms": resolve_ms})
            return []
        dialogs = state.filter_dialogs(dialogs)
        from app.services.adapters.telegram.history.dialog_rank import rank_dialogs

        dialogs = rank_dialogs(
            dialogs,
            preferred_sources=list(state.preferred_sources or []),
            hit_scores=dict(state.dialog_hit_scores or {}),
        )
        queries = _expanded_search_queries(title, keywords, max_queries=4)
        if not queries:
            return []

        options = self._history_options(config)
        from app.services.adapters.telegram.history.config import adaptive_messages_per_query

        tuned = adaptive_messages_per_query(options.messages_per_query)
        if tuned != options.messages_per_query:
            options = TelegramHistoryOptions(
                history_limit=options.history_limit,
                fallback_scan_limit=options.fallback_scan_limit,
                messages_per_query=tuned,
                total_budget=options.total_budget,
                query_budget=options.query_budget,
                recent_budget=options.recent_budget,
            )
        budget = TelegramSearchBudget(options.total_budget)
        add_log(
            "info",
            "telegram",
            "Telegram 历史搜索开始",
            {
                "title": title,
                "sources": len(dialogs),
                "queries": queries,
                "budget": options.total_budget,
                "resolve_ms": resolve_ms,
                "force_remote": state.force_remote,
                "preferred_sources": list(state.preferred_sources),
                "shared_seen_urls": len(state.seen_urls),
            },
        )
        metrics = TelegramSearchMetrics(resolve_ms=resolve_ms, dialogs=len(dialogs), force_remote=state.force_remote)
        indexed_results: list[SearchResult] = []
        if not state.force_remote:
            indexed_results = self._search_indexed_telegram_messages(dialogs, queries)
            if indexed_results:
                results = self._dedupe_results(state.remember_results(indexed_results))
                metrics.index_hits = len(results)
                metrics.extra["cache"] = extract_cache_stats()
                payload = {
                    "title": title,
                    "count": len(results),
                    "sources": len(dialogs),
                    "total_ms": _elapsed_ms(total_started),
                    **metrics.as_payload(),
                }
                add_log("info", "telegram", "Telegram 本地索引命中资源，跳过远端历史搜索", payload)
                add_log("info", "telegram", "Telegram 搜索指标", payload)
                record_telegram_search(payload)
                return results

        search_started = time.perf_counter()
        remote_results, search_metrics = await self._search_dialogs_concurrently(
            client,
            dialogs,
            queries,
            options,
            budget,
            incremental=incremental,
            shared_state=state,
        )
        all_results = [*indexed_results, *remote_results]
        metrics.search_ms = _elapsed_ms(search_started)
        metrics.extract_ms = int(search_metrics.get("extract_ms", 0) or 0)
        metrics.remote_hits = len(remote_results)
        metrics.cancelled = int(search_metrics.get("cancelled", 0) or 0)
        metrics.extra["cache"] = extract_cache_stats()
        metrics.extra["cancel_rate"] = round(
            metrics.cancelled / max(1, len(dialogs)),
            3,
        )

        results = self._dedupe_results(state.remember_results(all_results))
        payload = {
            "title": title,
            "count": len(results),
            "raw_count": len(all_results),
            "total_ms": _elapsed_ms(total_started),
            **metrics.as_payload(),
        }
        if budget.exhausted():
            add_log("warning", "telegram", "Telegram 历史搜索时间预算用尽，已提前返回已找到结果", {**payload, "budget": options.total_budget})
        add_log("info", "telegram", "Telegram 历史搜索完成", payload)
        add_log("info", "telegram", "Telegram 搜索指标", payload)
        record_telegram_search(payload)
        return results

    async def _resolve_dialogs_for_history_search(
        self,
        client: TelegramClient,
        source_values: list[str],
        state: TelegramSearchSharedState,
    ) -> list[dict[str, Any]]:
        if state.dialogs:
            return state.dialogs
        try:
            dialogs = await asyncio.wait_for(
                self._resolve_dialogs(client, source_values),
                timeout=max(8, min(25, len(source_values) * 8)),
            )
        except asyncio.TimeoutError:
            add_log(
                "warning",
                "telegram",
                "Telegram 群组/频道解析超时，使用原始配置继续搜索",
                {"sources": len(source_values)},
            )
            dialogs = [{"entity": source, "source": source, "canonical": source} for source in source_values]
        state.dialogs = dialogs
        return dialogs

    def _search_indexed_telegram_messages(self, dialogs: list[dict[str, Any]], queries: list[str]) -> list[SearchResult]:
        sources = [str(item["canonical"]) for item in dialogs if item.get("canonical") is not None]
        return search_telegram_message_index(sources, queries, TELEGRAM_HISTORY_MAX_RESULTS)

