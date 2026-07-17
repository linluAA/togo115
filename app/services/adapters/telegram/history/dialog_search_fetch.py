from __future__ import annotations

import asyncio
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.models import TelegramHistoryOptions
from app.services.adapters.telegram.rate_limit import telegram_request_gate
from app.services.adapters.telegram.scan.message_index import index_telegram_messages


class TelegramDialogSearchFetchMixin:
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
