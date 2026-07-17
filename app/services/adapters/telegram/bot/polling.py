from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.services.http_client import shared_async_client

from app.db import add_log
from app.services.integration_state import get_flow, module_proxy, save_flow


class TelegramBotPollingMixin:
    _polling_task: asyncio.Task | None = None
    _polling_token: str | None = None
    _poll_warning_last_seen: dict[tuple[str, str], float] = {}

    async def ensure_polling(self) -> None:
        config = self._config()
        token = str(config.get("bot_token") or "").strip()
        if not token:
            return
        cls = type(self)
        if cls._polling_task and not cls._polling_task.done() and cls._polling_token != token:
            await self.stop_polling()
        if cls._polling_task and cls._polling_task.done():
            task_error = self._polling_task_error(cls._polling_task)
            self._log_poll_exception(
                task_error or RuntimeError("polling task stopped"),
                action="restart-stopped-task",
                message="TG Bot 监听任务已停止，自动重启",
                retry_delay=0,
            )
            cls._polling_task = None
            cls._polling_token = None
        if cls._polling_task and not cls._polling_task.done():
            add_log("debug", "tg_bot", "TG Bot 监听心跳正常")
            return
        cls._polling_token = token
        cls._polling_task = asyncio.create_task(self._poll_updates(token), name="togo115-tg-bot")
        add_log("info", "tg_bot", "TG Bot 监听已启动")

    async def stop_polling(self) -> None:
        cls = type(self)
        if cls._polling_task and not cls._polling_task.done():
            cls._polling_task.cancel()
            try:
                await cls._polling_task
            except asyncio.CancelledError:
                pass
        cls._polling_task = None
        cls._polling_token = None

    async def _poll_updates(self, token: str) -> None:
        offset = int(get_flow("tg_bot").get("offset") or 0)
        retry_delay = 2.0
        while True:
            proxy = module_proxy("telegram")
            try:
                async with shared_async_client(proxy=proxy or None, timeout=35, follow_redirects=True) as client:
                    while True:
                        try:
                            offset = await self._poll_once(client, token, offset)
                            retry_delay = 2.0
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            self._log_poll_exception(
                                exc,
                                action="retry-poll",
                                message="TG Bot 监听异常，稍后重试",
                                retry_delay=retry_delay,
                            )
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 1.6, 30.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_poll_exception(
                    exc,
                    action="recreate-http-client",
                    message="TG Bot 监听客户端异常，正在重建连接",
                    retry_delay=retry_delay,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.6, 30.0)

    async def _poll_once(self, client: httpx.AsyncClient, token: str, offset: int) -> int:
        res = await client.get(self._api_url(token, "getUpdates"), params={"timeout": 25, "offset": offset})
        res.raise_for_status()
        payload = res.json()
        if not payload.get("ok"):
            self._log_poll_api_error(payload)
            await asyncio.sleep(5)
            return offset
        for update in payload.get("result", []):
            offset = int(update.get("update_id") or offset) + 1
            save_flow("tg_bot", {"offset": offset})
            await self._handle_update(client, token, update)
        return offset

    async def _handle_update(self, client: httpx.AsyncClient, token: str, update: dict[str, Any]) -> None:
        callback = update.get("callback_query") or {}
        if callback:
            await self._handle_callback(client, token, callback)
            return
        message = update.get("message") or update.get("edited_message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return
        config = self._config()
        if not self._chat_allowed(config, chat_id):
            await self._send_bot_message(client, token, chat_id, "当前 Chat ID 未授权。")
            add_log("warning", "tg_bot", "TG Bot 收到未授权消息", {"chat_id": chat_id})
            return
        reply = await self._command_reply(text, chat_id)
        if reply:
            await self._send_bot_message(client, token, chat_id, reply)

    def _log_poll_api_error(self, payload: dict[str, Any]) -> None:
        error_payload = self._api_error_payload(payload)
        level = "warning"
        message = "TG Bot 获取消息失败"
        if self._should_throttle_recoverable_poll_error(error_payload["category"], error_payload["action"]):
            level = "debug"
            message = "TG Bot 获取消息失败（同类异常已降噪）"
        add_log(level, "tg_bot", message, error_payload)

    def _log_poll_exception(self, exc: BaseException, *, action: str, message: str, retry_delay: float) -> None:
        payload = self._poll_error_payload(exc, action=action, recovered=True, retry_delay=retry_delay)
        level = "warning"
        if self._should_throttle_recoverable_poll_error(payload["category"], action):
            level = "debug"
            message = f"{message}（同类异常已降噪）"
        add_log(level, "tg_bot", message, payload)

    def _should_throttle_recoverable_poll_error(self, category: str, action: str) -> bool:
        if category not in {"timeout", "telegram-api", "network-or-proxy", "rate-limit", "polling-conflict"}:
            return False
        now = time.monotonic()
        key = (category, action)
        last_seen = type(self)._poll_warning_last_seen.get(key, 0.0)
        type(self)._poll_warning_last_seen[key] = now
        return now - last_seen < 60.0

    def _poll_error_payload(
        self,
        exc: BaseException | None,
        *,
        action: str,
        recovered: bool,
        retry_delay: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self._classify_poll_error(exc),
            "error": str(exc) if exc else "",
            "error_type": type(exc).__name__ if exc else None,
            "error_repr": repr(exc) if exc else None,
            "action": action,
            "recovered": recovered,
        }
        if retry_delay is not None:
            payload["retry_delay"] = retry_delay
        return payload

    def _api_error_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        description = str(payload.get("description") or "")
        return {
            "category": self._classify_api_error(payload),
            "response": payload,
            "error": description,
            "error_type": "TelegramApiError",
            "error_repr": repr(payload),
            "action": "retry-poll",
            "recovered": True,
        }

    def _classify_poll_error(self, exc: BaseException | None) -> str:
        if exc is None:
            return "task-stopped"
        text = f"{type(exc).__name__}: {exc!s} {exc!r}".casefold()
        if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)) or "timeout" in text or "timed out" in text:
            return "timeout"
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403, 404):
                return "auth-or-token"
            if status == 409:
                return "polling-conflict"
            if status == 429:
                return "rate-limit"
            if status >= 500:
                return "telegram-api"
        if isinstance(exc, httpx.HTTPError) or any(term in text for term in ("proxy", "connect", "network", "tls", "ssl", "connection")):
            return "network-or-proxy"
        return "unknown"

    def _classify_api_error(self, payload: dict[str, Any]) -> str:
        code = int(payload.get("error_code") or 0)
        description = str(payload.get("description") or "").casefold()
        if code in (401, 403, 404) or "token" in description or "unauthorized" in description:
            return "auth-or-token"
        if code == 409 or "terminated by other getupdates" in description or "conflict" in description:
            return "polling-conflict"
        if code == 429 or "too many requests" in description:
            return "rate-limit"
        if code >= 500:
            return "telegram-api"
        return "telegram-api"

    def _polling_task_error(self, task: asyncio.Task) -> BaseException | None:
        if task.cancelled():
            return None
        try:
            return task.exception()
        except asyncio.CancelledError:
            return None
