from __future__ import annotations

import asyncio
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services import concurrency as runtime
from app.services.link import TELEGRAM_HISTORY_MAX_RESULTS
from app.services.adapters.telegram.history.dialog_search_fetch import TelegramDialogSearchFetchMixin
from app.services.adapters.telegram.history.dialog_search_query import TelegramDialogSearchQueryMixin
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.types import SearchResult

TELEGRAM_DIALOG_SEARCH_CONCURRENCY = 3
TELEGRAM_HISTORY_RETURN_TARGET = 2


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
        semaphore = runtime.telegram_dialog_search_semaphore()
        all_results: list[SearchResult] = []
        state = shared_state or TelegramSearchSharedState()
        extract_ms_total = 0
        cancelled = 0

        async def search_one(dialog: dict[str, Any]) -> tuple[list[SearchResult], int]:
            if budget.exhausted() or len(all_results) >= TELEGRAM_HISTORY_RETURN_TARGET:
                return [], 0
            source_key = str(dialog.get("canonical") or dialog.get("source") or "")
            async with runtime.telegram_source_lock(source_key):
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
