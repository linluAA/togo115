from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services import concurrency as runtime
from app.services.adapters.telegram.scan.message_index import index_telegram_messages, search_telegram_message_index
from app.services.adapters.telegram.scan.extract_cache import (
    get_cached_message_extract,
    set_cached_message_extract,
)
from app.services.adapters.telegram.models import TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link import (
    expanded_search_queries as _expanded_search_queries,
    context_for_115_link,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult
from app.services.adapters.telegram.rate_limit import telegram_request_gate


TELEGRAM_FAST_DIALOG_SEARCH_CONCURRENCY = 6
TELEGRAM_FAST_RETURN_TARGET = 1
TELEGRAM_FAST_TOTAL_BUDGET_SECONDS = 5.0
TELEGRAM_FAST_QUERY_TIMEOUT_SECONDS = 0.9
TELEGRAM_FAST_MESSAGE_EXTRACT_TIMEOUT_SECONDS = 1.2
TELEGRAM_FAST_NEIGHBOR_TIMEOUT_SECONDS = 0.45
TELEGRAM_FAST_BUTTON_CLICK_TIMEOUT_SECONDS = 0.65


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


from app.services.adapters.telegram.history.fast_message import TelegramFastMessageMixin


class TelegramFastSearchMixin(TelegramFastMessageMixin):
    async def search_history_fast(
        self,
        title: str,
        keywords: list[str],
        *,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        """Return the first usable Telegram hit with a hard 5s budget for interactive subscription creation."""
        started = time.perf_counter()
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
        if state.dialogs:
            dialogs = state.dialogs
        else:
            dialogs = await self._resolve_dialogs_for_fast_search(client, source_values)
            state.dialogs = dialogs
        resolve_ms = _elapsed_ms(resolve_started)
        if not dialogs:
            return []
        dialogs = state.filter_dialogs(dialogs)
        queries = self._server_search_queries(_expanded_search_queries(title, keywords, max_queries=6))
        if not queries:
            return []
        if not state.force_remote:
            indexed_results = search_telegram_message_index([str(item["canonical"]) for item in dialogs], queries, TELEGRAM_FAST_RETURN_TARGET)
            if indexed_results:
                results = self._dedupe_results(state.remember_results(indexed_results))
                add_log("debug",
                    "telegram",
                    "Telegram 本地索引快速命中资源",
                    {"title": title, "count": len(results), "sources": len(dialogs), "resolve_ms": resolve_ms, "total_ms": _elapsed_ms(started)},
                )
                return results
        budget = TelegramSearchBudget(TELEGRAM_FAST_TOTAL_BUDGET_SECONDS)
        add_log("debug", "telegram", "Telegram 快速搜索开始", {**self._fast_search_start_payload(title, dialogs, queries[0]), "resolve_ms": resolve_ms})
        search_started = time.perf_counter()
        results = await self._search_dialogs_fast(client, dialogs, queries[0], budget, shared_state=state)
        add_log("debug",
            "telegram",
            "Telegram 快速搜索完成",
            {"title": title, "count": len(results), "resolve_ms": resolve_ms, "search_ms": _elapsed_ms(search_started), "total_ms": _elapsed_ms(started), "remaining_budget": round(budget.remaining, 2)},
        )
        return self._dedupe_results(state.remember_results(results))

    def _fast_search_start_payload(self, title: str, dialogs: list[dict[str, Any]], query: str) -> dict[str, Any]:
        return {"title": title, "sources": len(dialogs), "query": query, "budget": TELEGRAM_FAST_TOTAL_BUDGET_SECONDS}

    async def _resolve_dialogs_for_fast_search(self, client: TelegramClient, source_values: list[str]) -> list[dict[str, Any]]:
        try:
            timeout = max(1.0, min(2.5, len(source_values) * 0.7))
            return await asyncio.wait_for(self._resolve_dialogs(client, source_values), timeout=timeout)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("debug", "telegram", "Telegram 快速搜索来源解析超时，使用原始配置继续", {"sources": len(source_values), "error": str(exc), "error_type": type(exc).__name__})
            return [{"entity": source, "source": source, "canonical": source} for source in source_values]

    async def _search_dialogs_fast(
        self,
        client: TelegramClient,
        dialogs: list[dict[str, Any]],
        query: str,
        budget: TelegramSearchBudget,
        *,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        semaphore = runtime.telegram_dialog_search_semaphore()
        results: list[SearchResult] = []
        state = shared_state or TelegramSearchSharedState()
        tasks = [asyncio.create_task(self._guarded_fast_dialog_search(semaphore, client, dialog, query, budget, results, shared_state=state)) for dialog in dialogs]
        pending: set[asyncio.Task] = set(tasks)
        try:
            while pending and not budget.exhausted() and not results:
                done, pending = await asyncio.wait(pending, timeout=budget.timeout(0.5), return_when=asyncio.FIRST_COMPLETED)
                self._collect_fast_dialog_results(done, results)
        finally:
            await self._cancel_pending_dialog_searches(pending)
        return results[:TELEGRAM_FAST_RETURN_TARGET]

    async def _guarded_fast_dialog_search(
        self,
        semaphore: asyncio.Semaphore,
        client: TelegramClient,
        dialog: dict[str, Any],
        query: str,
        budget: TelegramSearchBudget,
        shared_results: list[SearchResult],
        *,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        source_key = str(dialog.get("canonical") or dialog.get("source") or "")
        async with runtime.telegram_source_lock(source_key):
            async with semaphore:
                if budget.exhausted() or shared_results:
                    return []
                return await self._search_dialog_fast(client, dialog, query, budget, shared_state=shared_state)

    def _collect_fast_dialog_results(self, done: set[asyncio.Task], results: list[SearchResult]) -> None:
        for task in done:
            try:
                hits = task.result()
            except Exception as exc:
                telegram_request_gate.note_error(exc)
                add_log("debug", "telegram", "Telegram 快速搜索单来源失败", {"error": str(exc), "error_type": type(exc).__name__})
                continue
            if hits:
                results.extend(hits)
                return

    async def _search_dialog_fast(
        self,
        client: TelegramClient,
        dialog: dict[str, Any],
        query: str,
        budget: TelegramSearchBudget,
        *,
        shared_state: TelegramSearchSharedState | None = None,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        source = str(dialog["canonical"])
        state = shared_state or TelegramSearchSharedState()
        messages = await self._get_fast_search_messages(client, dialog["entity"], query, budget)
        self._index_fast_messages(source, messages)
        read_ms = _elapsed_ms(started)
        extract_started = time.perf_counter()
        seen_messages = state.seen_messages_for(source)
        for message in messages[:2]:
            hits = await self._extract_fast_message_hits(client, dialog["entity"], source, message, query, budget)
            if hits and not self._pipeline_is_seen(message, seen_messages, TelegramPipelineStats()):
                self._pipeline_mark_seen(message, seen_messages)
                add_log("debug", "telegram", "Telegram 快速搜索单来源命中", {"dialog": source, "query": query, "messages": len(messages), "links": len(hits), "read_ms": read_ms, "extract_ms": _elapsed_ms(extract_started)})
                return hits
        add_log("debug", "telegram", "Telegram 快速搜索单来源无结果", {"dialog": source, "query": query, "messages": len(messages), "read_ms": read_ms, "extract_ms": _elapsed_ms(extract_started)})
        return []

    async def _extract_fast_message_hits(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        message: Any,
        query: str,
        budget: TelegramSearchBudget,
    ) -> list[SearchResult]:
        if budget.exhausted():
            return []
        try:
            return await asyncio.wait_for(
                self._fast_links_from_message(client, entity, source, message, [query]),
                timeout=budget.timeout(TELEGRAM_FAST_MESSAGE_EXTRACT_TIMEOUT_SECONDS),
            )
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("debug", "telegram", "Telegram 快速搜索链接提取失败", {"dialog": source, "query": query, "error": str(exc), "error_type": type(exc).__name__})
            return []

    async def _get_fast_search_messages(self, client: TelegramClient, entity: Any, query: str, budget: TelegramSearchBudget) -> list[Any]:
        get_messages = getattr(client, "get_messages", None)
        if not callable(get_messages):
            return []
        try:
            messages = await asyncio.wait_for(get_messages(entity, search=query, limit=2), timeout=budget.timeout(TELEGRAM_FAST_QUERY_TIMEOUT_SECONDS))
            return messages if isinstance(messages, list) else list(messages or [])
        except Exception:
            return []

    def _index_fast_messages(self, source: str, messages: list[Any]) -> None:
        try:
            index_telegram_messages(source, messages)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log("debug", "telegram", "Telegram 快速搜索索引写入失败", {"dialog": source, "error": str(exc), "error_type": type(exc).__name__})

