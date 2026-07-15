from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.adapters.telegram.scan.message_index import index_telegram_messages
from app.services.search_metrics import record_prewarm


TELEGRAM_INDEX_PREWARM_LIMIT = 40
TELEGRAM_INDEX_PREWARM_DIALOG_CONCURRENCY = 2


class TelegramIndexPrewarmMixin:
    async def prewarm_message_index(self, *, limit_per_source: int = TELEGRAM_INDEX_PREWARM_LIMIT) -> dict[str, int]:
        """Incrementally index recent messages from configured sources for faster future searches."""
        started = time.perf_counter()
        client = await self._authorized_client_for_search()
        if client is None:
            return {"sources": 0, "indexed": 0, "dialogs": 0}
        config = self._config()
        source_values = self._configured_sources(config)
        if not source_values:
            return {"sources": 0, "indexed": 0, "dialogs": 0}
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
            return {"sources": len(source_values), "indexed": 0, "dialogs": 0}
        if not dialogs:
            return {"sources": len(source_values), "indexed": 0, "dialogs": 0}

        semaphore = asyncio.Semaphore(TELEGRAM_INDEX_PREWARM_DIALOG_CONCURRENCY)
        total_indexed = 0

        async def prewarm_one(dialog: dict[str, Any]) -> int:
            async with semaphore:
                await telegram_request_gate.wait()
                return await self._prewarm_dialog_index(client, dialog, limit_per_source)

        counts = await asyncio.gather(*(prewarm_one(dialog) for dialog in dialogs), return_exceptions=True)
        for item in counts:
            if isinstance(item, int):
                total_indexed += item
            elif isinstance(item, Exception):
                telegram_request_gate.note_error(item)
        payload = {
            "sources": len(source_values),
            "dialogs": len(dialogs),
            "indexed": total_indexed,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "gate": telegram_request_gate.stats(),
        }
        record_prewarm(payload)
        add_log("info", "telegram", "Telegram 索引预热完成", payload)
        return payload

    async def _prewarm_dialog_index(self, client: TelegramClient, dialog: dict[str, Any], limit: int) -> int:
        entity = dialog.get("entity")
        source = str(dialog.get("canonical") or dialog.get("source") or "")
        if entity is None or not source:
            return 0
        get_messages = getattr(client, "get_messages", None)
        if not callable(get_messages):
            return 0
        try:
            messages = await asyncio.wait_for(get_messages(entity, limit=max(5, min(int(limit), 80))), timeout=8)
            items = messages if isinstance(messages, list) else list(messages or [])
            count = index_telegram_messages(source, items)
            telegram_request_gate.note_success()
            return int(count or 0)
        except Exception as exc:
            telegram_request_gate.note_error(exc)
            add_log(
                "debug",
                "telegram",
                "Telegram 索引预热单源失败",
                {"dialog": source, "error": str(exc), "error_type": type(exc).__name__},
            )
            return 0
