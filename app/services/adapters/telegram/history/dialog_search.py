from __future__ import annotations

import asyncio
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services import concurrency as runtime
from app.services.link import TELEGRAM_HISTORY_MAX_RESULTS
from app.services.adapters.telegram.history.dialog_rank import note_dialog_hit, rank_dialogs
from app.services.adapters.telegram.history.dialog_search_fetch import TelegramDialogSearchFetchMixin
from app.services.adapters.telegram.history.dialog_search_query import TelegramDialogSearchQueryMixin
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.types import SearchResult

TELEGRAM_DIALOG_SEARCH_CONCURRENCY = 3
TELEGRAM_HISTORY_RETURN_TARGET = 2
# Stop remaining dialogs after this many consecutive empties when still zero hits.
TELEGRAM_EMPTY_DIALOG_STREAK = 4


class TelegramDialogSearchMixin(TelegramDialogSearchQueryMixin, TelegramDialogSearchFetchMixin):
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
        all_results: list[SearchResult] = []
        state = shared_state or TelegramSearchSharedState()
        extract_ms_total = 0
        searched = 0
        failed = 0
        ranked_dialogs = rank_dialogs(
            dialogs,
            preferred_sources=list(state.preferred_sources or []),
            hit_scores=dict(state.dialog_hit_scores or {}),
        )
        semaphore = runtime.telegram_dialog_search_semaphore()

        async def search_one(index: int, dialog: dict[str, Any]) -> tuple[int, list[SearchResult], int, bool, bool]:
            if budget.exhausted():
                return index, [], 0, False, False
            try:
                async with semaphore:
                    if budget.exhausted():
                        return index, [], 0, False, False
                    hits, dialog_extract_ms = await self._search_single_dialog_reliably(
                        client,
                        dialog,
                        queries,
                        options,
                        budget,
                        incremental=incremental,
                        shared_state=state,
                    )
            except Exception as exc:
                telegram_request_gate.note_error(exc)
                add_log(
                    "warning",
                    "telegram",
                    "Telegram 来源搜索失败，已跳过单个来源",
                    {"source": dialog.get("canonical") or dialog.get("source"), "error": str(exc), "error_type": type(exc).__name__},
                )
                return index, [], 0, False, True
            return index, hits, int(dialog_extract_ms or 0), True, False

        tasks = [asyncio.create_task(search_one(index, dialog)) for index, dialog in enumerate(ranked_dialogs)]
        completed: list[tuple[int, list[SearchResult]]] = []
        for task in asyncio.as_completed(tasks):
            index, hits, dialog_extract_ms, did_search, did_fail = await task
            if did_fail:
                failed += 1
            if did_search:
                searched += 1
                extract_ms_total += dialog_extract_ms
            if hits:
                completed.append((index, hits))
        for _index, hits in sorted(completed, key=lambda item: item[0]):
            all_results.extend(hits)
        deduped_results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for result in all_results:
            url = str(getattr(result, "url", "") or "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            deduped_results.append(result)
        return deduped_results[:TELEGRAM_HISTORY_MAX_RESULTS], {
            "extract_ms": extract_ms_total,
            "cancelled": 0,
            "searched_dialogs": searched,
            "failed_dialogs": failed,
        }

    async def _search_single_dialog_reliably(
        self,
        client: TelegramClient,
        dialog: dict[str, Any],
        queries: list[str],
        options: TelegramHistoryOptions,
        budget: TelegramSearchBudget,
        *,
        incremental: bool,
        shared_state: TelegramSearchSharedState,
    ) -> tuple[list[SearchResult], int]:
        source_key = str(dialog.get("canonical") or dialog.get("source") or "")
        async with runtime.telegram_source_lock(source_key):
            await telegram_request_gate.wait()
            hits, dialog_extract_ms = await self._search_dialog_history(
                client,
                dialog,
                queries,
                options,
                budget,
                incremental=incremental,
                shared_state=shared_state,
                stop_event=None,
            )
        if hits and source_key:
            shared_state.note_dialog_hits(source_key, len(hits))
            note_dialog_hit(source_key, len(hits))
        return hits, dialog_extract_ms

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
            category = self._classify_client_error(exc)
            self._remember_current_client_init_failure(exc)
            self._log_client_init_failure(exc, category, action="search-client-init", recovered=False)
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
