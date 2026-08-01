from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.history.dialog_rank import note_dialog_latency
from app.services.adapters.telegram.history.dialog_search_query_run import (
    TelegramDialogQueryExecutorMixin,
    _elapsed_ms,
)
from app.services.link import (
    TELEGRAM_HISTORY_MAX_RESULTS,
    context_for_115_link,
    extract_115_links,
    local_text_matches_query,
    message_has_link_button_hint,
    telegram_message_text,
    text_has_external_resource_page_hint,
)
from app.services.adapters.telegram.scan.message_links_filter import _restore_query_title_context
from app.services.adapters.telegram.scan.message_titles import _telegram_resource_title
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.types import SearchResult


class TelegramDialogSearchQueryMixin(TelegramDialogQueryExecutorMixin):
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
        stop_event: asyncio.Event | None = None,
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
        if not incremental and not budget.exhausted() and not (stop_event is not None and stop_event.is_set()):
            server_started = time.perf_counter()
            query_limit = 1 if options.total_budget > 0 and budget.remaining < options.total_budget * 0.35 else 2
            for query in self._server_search_queries(queries, limit=query_limit):
                if budget.exhausted() or len(results) >= TELEGRAM_HISTORY_MAX_RESULTS:
                    break
                if stop_event is not None and stop_event.is_set():
                    break
                hits = await self._search_dialog_query(
                    client, entity, source, query, options, budget, seen_messages, stats, shared_state=state
                )
                results.extend(hits)
                # First successful server query is enough for this dialog.
                if hits:
                    break
            server_ms = _elapsed_ms(server_started)
            if results:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 服务端搜索已命中，跳过最近消息兜底扫描",
                    {"dialog": source, "links": len(results), "server_ms": server_ms},
                )

        if not results and not budget.exhausted() and not (stop_event is not None and stop_event.is_set()):
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
        note_dialog_latency(source, total_ms, had_hits=bool(results))
        return results, extract_ms

    def _message_suggests_resource_links(self, message: Any) -> bool:
        text = telegram_message_text(message)
        if not text and not message_has_link_button_hint(message):
            return False
        lowered = text.casefold()
        return bool(
            extract_115_links(text)
            or "magnet:?" in lowered
            or text_has_external_resource_page_hint(text)
            or message_has_link_button_hint(message)
        )

    async def _body_only_extract_message_links(
        self,
        source: str,
        message: Any,
        query: str,
        seen_messages: set[int],
        pipeline_stats: TelegramPipelineStats,
    ) -> list[SearchResult]:
        """Cheap extract: only parse 115/magnet from the message body, no neighbors/buttons/pages."""
        try:
            message_id = int(getattr(message, "id", 0) or 0)
        except (TypeError, ValueError):
            message_id = 0
        if message_id and message_id in seen_messages:
            pipeline_stats.duplicate_messages += 1
            return []
        text = telegram_message_text(message)
        urls = list(extract_115_links(text) or [])
        if "magnet:?" in text.casefold():
            for token in text.split():
                token = token.strip().strip("<>\"'()[]")
                if token.casefold().startswith("magnet:?") and token not in urls:
                    urls.append(token)
        if not urls:
            pipeline_stats.no_link += 1
            pipeline_stats.skipped_no_link_hint += 1
            return []
        hits: list[SearchResult] = []
        for url in urls:
            scoped = context_for_115_link(text, url, max(len(urls), 2)) if "115" in url else text
            scoped = _restore_query_title_context(text, scoped, [query]) if "115" in url else scoped
            title = (
                _telegram_resource_title(scoped)
                if "115" in url
                else (scoped.splitlines()[0][:120] if scoped else query)
            )
            if not local_text_matches_query(scoped, query):
                continue
            if title and not str(title).startswith("Telegram ") and not local_text_matches_query(title, query):
                continue
            hits.append(
                SearchResult(
                    title=title or query,
                    url=url,
                    source=source,
                    message_id=str(message_id or "") or None,
                    context=scoped or text,
                )
            )
        if message_id:
            seen_messages.add(message_id)
        pipeline_stats.extracted_links += len(hits)
        return hits
