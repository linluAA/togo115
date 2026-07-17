from __future__ import annotations

import asyncio
from typing import Any, Callable

from telethon import TelegramClient, events

from app.db import add_log
from app.services.adapters.telegram.scan.message_index import index_telegram_messages
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link_parser import telegram_message_text


class TelegramMonitorMixin:
    async def ensure_monitoring(self) -> None:
        if not await self.is_authorized():
            return
        cls = type(self)
        client = await self.client()
        source_values = self._configured_sources(self._config())
        if not source_values:
            return
        dialogs = await self._resolve_dialogs(client, source_values)
        if not dialogs:
            return

        source_key = tuple(str(item["canonical"]) for item in dialogs)
        listener_alive = self._reset_dead_listener_if_needed(source_key)
        if self._monitor_is_healthy(listener_alive, source_key):
            return
        self._prepare_handler_registration(client, listener_alive, source_key)
        self._register_event_handler_if_needed(client, dialogs, source_key)
        self._start_listener_if_needed(client, listener_alive, source_key)

    def _reset_dead_listener_if_needed(self, source_key: tuple[str, ...]) -> bool:
        cls = type(self)
        listener_alive = bool(cls._listener_task and not cls._listener_task.done())
        if cls._listener_task and cls._listener_task.done():
            task_error = None
            if not cls._listener_task.cancelled():
                task_error = cls._listener_task.exception()
            add_log(
                "warning",
                "telegram",
                "Telegram 监听任务已停止，准备自动重建",
                {
                    "category": "listener-stopped",
                    "error_type": type(task_error).__name__ if task_error else None,
                    "error_repr": repr(task_error) if task_error else None,
                    "action": "reset-listener-and-handler",
                    "recovered": True,
                    "sources": list(source_key),
                },
            )
            cls._listener_task = None
            cls._handler_registered = False
            cls._handler = None
            cls._handler_sources = ()
            listener_alive = False
        return listener_alive

    def _monitor_is_healthy(self, listener_alive: bool, source_key: tuple[str, ...]) -> bool:
        cls = type(self)
        if listener_alive and cls._handler_registered and cls._handler_sources == source_key:
            add_log("debug", "telegram", "Telegram 监控心跳正常")
            return True
        return False

    def _prepare_handler_registration(self, client: TelegramClient, listener_alive: bool, source_key: tuple[str, ...]) -> None:
        cls = type(self)
        if cls._handler_registered and cls._handler is not None:
            client.remove_event_handler(cls._handler)
            source_changed = cls._handler_sources != source_key
            cls._handler_registered = False
            cls._handler = None
            cls._handler_sources = ()
            add_log(
                "info",
                "telegram",
                "Telegram 监控来源已变更，重新注册监听" if source_changed else "Telegram 监控连接已重建，重新注册监听",
                {"sources": list(source_key), "action": "register-handler", "recovered": True},
            )
        elif listener_alive and not cls._handler_registered:
            add_log(
                "warning",
                "telegram",
                "Telegram 监听状态不一致，重新注册监听",
                {"sources": list(source_key), "action": "register-handler", "recovered": True},
            )

    def _register_event_handler_if_needed(self, client: TelegramClient, dialogs: list[dict[str, Any]], source_key: tuple[str, ...]) -> None:
        cls = type(self)
        if not cls._handler_registered:
            handler = self._build_event_handler(client)
            client.add_event_handler(handler, events.NewMessage(chats=[item["entity"] for item in dialogs]))
            cls._handler_registered = True
            cls._handler = handler
            cls._handler_sources = source_key

    def _start_listener_if_needed(self, client: TelegramClient, listener_alive: bool, source_key: tuple[str, ...]) -> None:
        cls = type(self)
        if not listener_alive:
            cls._listener_task = asyncio.create_task(client.run_until_disconnected())
            add_log("info", "telegram", "Telegram 实时监控已启动", {"sources": list(source_key)})

    def _build_event_handler(self, client: TelegramClient) -> Callable[[Any], Any]:
        async def handler(event) -> None:
            from app.services.application import attach_results_to_matching_subscriptions

            source = str(getattr(event, "chat_id", "") or "telegram")
            message = getattr(event, "message", None)
            if message is not None:
                self._index_realtime_message(source, message)
            pipeline_stats = TelegramPipelineStats(read=1)
            results = await self._pipeline_extract_message_links(
                client,
                getattr(event, "chat", None),
                source,
                message,
                [],
                None,
                set(),
                pipeline_stats,
                stage="realtime",
            )
            if not results:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 实时消息未提取到资源链接",
                    {"chat_id": getattr(event, "chat_id", None), "message_id": getattr(message, "id", None), **pipeline_stats.as_payload()},
                )
                return
            attached = await attach_results_to_matching_subscriptions(results, telegram_message_text(message))
            if not attached:
                add_log(
                    "debug",
                    "telegram",
                    "Telegram 实时消息提取到链接但未匹配任何订阅",
                    {"chat_id": getattr(event, "chat_id", None), "message_id": getattr(message, "id", None), "links": len(results)},
                )

        return handler

    def _index_realtime_message(self, source: str, message: Any) -> None:
        try:
            index_telegram_messages(source, [message])
        except Exception as exc:
            add_log("debug", "telegram", "Telegram 实时消息索引写入失败", {"dialog": source, "error": str(exc), "error_type": type(exc).__name__})
