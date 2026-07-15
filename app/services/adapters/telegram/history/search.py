

from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.history.config import build_history_options, server_search_queries
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.history.metrics import TelegramSearchMetrics
from app.services.adapters.telegram.scan.extract_cache import extract_cache_stats
from app.services.search_metrics import record_telegram_search
from app.services.adapters.telegram.history.fast import TelegramFastSearchMixin
from app.services.adapters.telegram.history.prewarm import TelegramIndexPrewarmMixin
from app.services.adapters.telegram.scan.message_index import index_telegram_messages, search_telegram_message_index
from app.services.adapters.telegram.history.recent import TelegramRecentScanMixin
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link_parser import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    _expanded_search_queries,
)
from app.services.types import SearchResult
from app.services.adapters.telegram.rate_limit import telegram_request_gate


TELEGRAM_DIALOG_SEARCH_CONCURRENCY = 3
TELEGRAM_HISTORY_RETURN_TARGET = 2


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class TelegramHistorySearchMixin(TelegramFastSearchMixin, TelegramRecentScanMixin, TelegramIndexPrewarmMixin):
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
        queries = _expanded_search_queries(title, keywords, max_queries=6)
        if not queries:
            return []

        options = self._history_options(config)
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

    async def _search_dialogs_concurrently(
        self,
        client: TelegramClient,
        dialogs: list[dict[str, Any]],
        queries: list[str],
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        *,
        incremental: bool = False,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> tuple[list[SearchResult], dict[str, int]]:
        semaphore = asyncio.Semaphore(TELEGRAM_DIALOG_SEARCH_CONCURRENCY)
        all_results: list[SearchResult] = []
        state = shared_state or TelegramSearchSharedState()
        extract_ms_total = 0
        cancelled = 0

        async def search_one(dialog: dict[str, Any]) -> tuple[list[SearchResult], int]:
            if budget.exhausted() or len(all_results) >= TELEGRAM_HISTORY_RETURN_TARGET:
                return [], 0
            async with semaphore:
                if budget.exhausted() or len(all_results) >= TELEGRAM_HISTORY_RETURN_TARGET:
                    return [], 0
                await telegram_request_gate.wait()
                return await self._search_dialog_history(
                    client,
                    dialog,
                    queries,
                    options,
                    budget,
                    incremental=incremental,
                    shared_state=state,
                )

        tasks = [asyncio.create_task(search_one(dialog)) for dialog in dialogs]
        pending: set[asyncio.Task] = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, timeout=budget.timeout(1.0), return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    if budget.exhausted():
                        break
                    continue
                for task in done:
                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        cancelled += 1
                        continue
                    except Exception as exc:
                        telegram_request_gate.note_error(exc)
                        add_log("warning", "telegram", "Telegram 来源并发搜索失败，已跳过单个来源", {"error": str(exc), "error_type": type(exc).__name__})
                        continue
                    if isinstance(result, tuple):
                        hits, dialog_extract_ms = result
                    else:
                        hits, dialog_extract_ms = result, 0
                    all_results.extend(hits)
                    extract_ms_total += int(dialog_extract_ms or 0)
                    if len(all_results) >= TELEGRAM_HISTORY_RETURN_TARGET:
                        cancelled += len(pending)
                        await self._cancel_pending_dialog_searches(pending)
                        return all_results[:TELEGRAM_HISTORY_MAX_RESULTS], {"extract_ms": extract_ms_total, "cancelled": cancelled}
                if budget.exhausted() or len(all_results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                    break
        finally:
            await self._cancel_pending_dialog_searches(pending)
        return all_results[:TELEGRAM_HISTORY_MAX_RESULTS], {"extract_ms": extract_ms_total, "cancelled": cancelled}

    async def _cancel_pending_dialog_searches(self, pending: set[asyncio.Task]) -> None:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _authorized_client_for_search(self) -> TelegramClient | None:
        try:
            client = await asyncio.wait_for(self.client(), timeout=15)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("warning", "telegram", "Telegram 客户端初始化失败", {"error": str(exc), "error_type": type(exc).__name__})
            return None
        try:
            authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=8)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("warning", "telegram", "Telegram 授权状态检查失败", {"error": str(exc), "error_type": type(exc).__name__})
            return None
        if not authorized:
            add_log("warning", "telegram", "Telegram 未登录，跳过历史搜索")
            return None
        return client

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

    async def _get_search_messages(
        self,
        client: TelegramClient,
        entity: Any,
        query: str,
        options: TelegramHistoryOptions,
    ) -> list[Any]:
        get_messages = getattr(client, "get_messages", None)
        limit = min(options.history_limit, options.messages_per_query)
        if callable(get_messages):
            try:
                messages = await asyncio.wait_for(get_messages(entity, search=query, limit=limit), timeout=2)
                items = messages if isinstance(messages, list) else list(messages or [])
                if items:
                    add_log("debug", "telegram", "Telegram get_messages 历史查询成功", {"query": query, "limit": limit, "count": len(items)})
                    return items
                add_log("debug", "telegram", "Telegram get_messages 历史查询为空，回退 iter_messages", {"query": query, "limit": limit})
            except asyncio.TimeoutError:
                add_log("debug", "telegram", "Telegram get_messages 历史查询超时，回退 iter_messages", {"query": query, "limit": limit, "timeout": 2})
            except Exception as exc:
                telegram_request_gate.note_error(exc)
                add_log("debug", "telegram", "Telegram get_messages 历史查询失败，回退 iter_messages", {"query": query, "limit": limit, "error": str(exc), "error_type": type(exc).__name__})
        try:
            messages = await asyncio.wait_for(self._iter_search_messages(client, entity, query, limit), timeout=3)
            if messages:
                add_log("debug", "telegram", "Telegram iter_messages 历史查询成功", {"query": query, "limit": limit, "count": len(messages)})
            return messages
        except asyncio.TimeoutError:
            add_log("warning", "telegram", "Telegram iter_messages 历史查询超时", {"query": query, "limit": limit, "timeout": 3})
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("warning", "telegram", "Telegram iter_messages 历史查询失败", {"query": query, "limit": limit, "error": str(exc), "error_type": type(exc).__name__})
        return []

    async def _iter_search_messages(self, client: TelegramClient, entity: Any, query: str, limit: int) -> list[Any]:
        messages: list[Any] = []
        async for message in client.iter_messages(entity, search=query, limit=limit, wait_time=0):
            messages.append(message)
        return messages

    def _index_telegram_messages(self, source: str, messages: list[Any]) -> None:
        try:
            count = index_telegram_messages(source, messages)
            if count:
                add_log("debug", "telegram", "Telegram 消息已写入本地索引", {"dialog": source, "count": count})
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("debug", "telegram", "Telegram 消息索引写入失败，继续远端搜索", {"dialog": source, "error": str(exc), "error_type": type(exc).__name__})
