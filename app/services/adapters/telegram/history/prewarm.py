from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services import concurrency as runtime
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.adapters.telegram.scan.message_index import index_telegram_messages, max_indexed_message_id
from app.services.search_metrics import record_prewarm


TELEGRAM_INDEX_PREWARM_LIMIT = 60
TELEGRAM_INDEX_PREWARM_DIALOG_CONCURRENCY = 3
# When a source is already warm, only pull a small recent window to catch new posts.
TELEGRAM_INDEX_PREWARM_DELTA_LIMIT = 30


class TelegramIndexPrewarmMixin:
    async def prewarm_message_index(self, *, limit_per_source: int = TELEGRAM_INDEX_PREWARM_LIMIT) -> dict[str, int]:
        """Incrementally index recent messages from configured sources for faster future searches."""
        started = time.perf_counter()
        client = await self._authorized_client_for_search()
        if client is None:
            return {"sources": 0, "indexed": 0, "dialogs": 0, "skipped_warm": 0}
        config = self._config()
        source_values = self._configured_sources(config)
        if not source_values:
            return {"sources": 0, "indexed": 0, "dialogs": 0, "skipped_warm": 0}
        try:
            dialogs = await asyncio.wait_for(self._resolve_dialogs(client, source_values), timeout=20)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log(
                "warning",
                "telegram",
                "Telegram 索引预热解析来源失败",
                {"error": str(exc), "error_type": type(exc).__name__},
            )
            return {"sources": len(source_values), "indexed": 0, "dialogs": 0, "skipped_warm": 0}
        if not dialogs:
            return {"sources": len(source_values), "indexed": 0, "dialogs": 0, "skipped_warm": 0}

        semaphore = runtime.telegram_dialog_search_semaphore()
        total_indexed = 0
        skipped_warm = 0

        async def prewarm_one(dialog: dict[str, Any]) -> tuple[int, int]:
            async with semaphore:
                await telegram_request_gate.wait()
                return await self._prewarm_dialog_index(client, dialog, limit_per_source)

        counts = await asyncio.gather(*(prewarm_one(dialog) for dialog in dialogs), return_exceptions=True)
        for item in counts:
            if isinstance(item, tuple) and len(item) == 2:
                total_indexed += int(item[0] or 0)
                skipped_warm += int(item[1] or 0)
            elif isinstance(item, int):
                total_indexed += item
            elif isinstance(item, Exception):
                telegram_request_gate.note_error(item)
        payload = {
            "sources": len(source_values),
            "dialogs": len(dialogs),
            "indexed": total_indexed,
            "skipped_warm": skipped_warm,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "gate": telegram_request_gate.stats(),
        }
        record_prewarm(payload)
        add_log("info", "telegram", "Telegram 索引预热完成", payload)
        return payload

    async def _prewarm_dialog_index(self, client: TelegramClient, dialog: dict[str, Any], limit: int) -> tuple[int, int]:
        entity = dialog.get("entity")
        source = str(dialog.get("canonical") or dialog.get("source") or "")
        if entity is None or not source:
            return (0, 0)
        get_messages = getattr(client, "get_messages", None)
        if not callable(get_messages):
            return (0, 0)
        already = max_indexed_message_id(source)
        # Warm sources only need a small recent window; cold sources get the full limit.
        fetch_limit = TELEGRAM_INDEX_PREWARM_DELTA_LIMIT if already > 0 else max(8, min(int(limit), 100))
        try:
            messages = await asyncio.wait_for(get_messages(entity, limit=fetch_limit), timeout=8)
            items = messages if isinstance(messages, list) else list(messages or [])
            if already > 0:
                fresh = [item for item in items if int(getattr(item, "id", 0) or 0) > already]
                skipped = 1 if items and not fresh else 0
                if not fresh:
                    telegram_request_gate.note_success()
                    return (0, skipped)
                items = fresh
            else:
                skipped = 0
            count = index_telegram_messages(source, items)
            telegram_request_gate.note_success()
            return (int(count or 0), skipped)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log(
                "debug",
                "telegram",
                "Telegram 索引预热单源失败",
                {"dialog": source, "error": str(exc), "error_type": type(exc).__name__},
            )
            return (0, 0)
