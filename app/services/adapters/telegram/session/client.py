from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.sessions import SQLiteSession

from app.db import add_log
from app.services.adapters.telegram.session.client_errors import (
    classify_client_error,
    log_client_init_failure,
)
from app.services.adapters.telegram.session.client_proxy import telethon_proxy
from app.services.integration_state import module_proxy

TELEGRAM_SESSION_BUSY_TIMEOUT_MS = 15000
TELEGRAM_SESSION_CONNECT_TIMEOUT_SECONDS = 15
TELEGRAM_CLIENT_CONNECT_RETRIES = 3
TELEGRAM_CLIENT_CONNECT_RETRY_DELAY_SECONDS = 0.35


class BusyTimeoutSQLiteSession(SQLiteSession):
    def _cursor(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.filename,
                timeout=TELEGRAM_SESSION_CONNECT_TIMEOUT_SECONDS,
                check_same_thread=False,
            )
            self._conn.execute(f"PRAGMA busy_timeout = {TELEGRAM_SESSION_BUSY_TIMEOUT_MS}")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        return self._conn.cursor()


class TelegramSessionClientMixin:
    async def client(self) -> TelegramClient:
        cls = type(self)
        loop = asyncio.get_running_loop()
        if cls._client and cls._client_loop is loop and cls._client.is_connected():
            return cls._client
        lock = self._get_client_init_lock(loop)
        async with lock:
            if cls._client and cls._client_loop is loop and cls._client.is_connected():
                return cls._client
            if cls._client and cls._client.is_connected():
                await cls._client.disconnect()
            config = self._config()
            proxy = self._telethon_proxy(module_proxy("telegram"))
            try:
                cls._client = await self._connect_client_with_retry(config, proxy)
            except Exception:
                await self._reset_client_state()
                raise
            cls._client_loop = loop
            return cls._client

    def _get_client_init_lock(self, loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
        cls = type(self)
        lock = getattr(cls, "_client_init_lock_instance", None)
        lock_loop = getattr(cls, "_client_init_lock_loop", None)
        if lock is None or lock_loop is not loop:
            lock = asyncio.Lock()
            cls._client_init_lock_instance = lock
            cls._client_init_lock_loop = loop
        return lock

    async def _connect_client_with_retry(self, config: dict[str, Any], proxy) -> TelegramClient:
        last_error: Exception | None = None
        for attempt in range(TELEGRAM_CLIENT_CONNECT_RETRIES):
            client = self._build_telegram_client(config, proxy)
            try:
                await asyncio.wait_for(client.connect(), timeout=12)
                if attempt > 0:
                    add_log(
                        "info",
                        "telegram",
                        "Telegram 客户端初始化已自动恢复",
                        {
                            "category": self._classify_client_error(last_error) if last_error else "unknown",
                            "attempt": attempt + 1,
                            "action": "connect-recovered",
                            "recovered": True,
                        },
                    )
                return client
            except Exception as exc:
                last_error = exc
                category = self._classify_client_error(exc)
                await self._safe_disconnect_client(client)
                retry = await self._handle_client_connect_failure(exc, category, attempt)
                if retry:
                    continue
                raise
        raise last_error or RuntimeError("Telegram 客户端初始化失败")

    def _build_telegram_client(self, config: dict[str, Any], proxy) -> TelegramClient:
        return TelegramClient(
            BusyTimeoutSQLiteSession(str(self._session_path())),
            int(config["api_id"]),
            config["api_hash"],
            proxy=proxy,
        )

    async def _safe_disconnect_client(self, client: TelegramClient) -> None:
        try:
            await client.disconnect()
        except Exception:
            pass

    async def _handle_client_connect_failure(self, exc: Exception, category: str, attempt: int) -> bool:
        if category == "session-corrupt":
            await self._handle_corrupt_session(exc, attempt)
        can_retry = attempt < TELEGRAM_CLIENT_CONNECT_RETRIES - 1 and category in {
            "session-locked",
            "timeout",
            "network-or-proxy",
        }
        action = "reset-client-and-retry" if category == "session-locked" else "retry-connect"
        if can_retry:
            if category == "session-locked":
                await self._reset_client_state()
            self._log_client_init_failure(
                exc,
                category,
                action=action,
                recovered=category == "session-locked",
                attempt=attempt + 1,
            )
            await asyncio.sleep(TELEGRAM_CLIENT_CONNECT_RETRY_DELAY_SECONDS * (attempt + 1))
            return True
        self._log_client_init_failure(exc, category, action="fail", recovered=False, attempt=attempt + 1)
        return False

    async def _handle_corrupt_session(self, exc: Exception, attempt: int) -> None:
        quarantined = self._quarantine_session_file()
        await self._reset_client_state()
        self._log_client_init_failure(
            exc,
            "session-corrupt",
            action="quarantine-and-reset",
            recovered=bool(quarantined),
            attempt=attempt + 1,
            extra={"quarantined_path": quarantined} if quarantined else None,
        )

    async def _reset_client_state(self) -> None:
        cls = type(self)
        client = getattr(cls, "_client", None)
        cls._client = None
        cls._client_loop = None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    def _quarantine_session_file(self) -> str | None:
        session_file = self._session_file_path()
        if not session_file.exists():
            return None
        broken_path = session_file.with_name(f"{session_file.name}.broken.{int(time.time())}")
        try:
            session_file.replace(broken_path)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(session_file) + suffix)
                if sidecar.exists():
                    sidecar.replace(Path(str(broken_path) + suffix))
            return str(broken_path)
        except Exception as exc:
            add_log(
                "warning",
                "telegram",
                "Telegram 会话文件隔离失败",
                {
                    "category": "session-corrupt",
                    "error_type": type(exc).__name__,
                    "error_repr": repr(exc),
                    "session_path": str(session_file),
                    "action": "quarantine-session",
                    "recovered": False,
                },
            )
            return None

    def _classify_client_error(self, exc: Exception) -> str:
        return classify_client_error(exc)

    def _log_client_init_failure(
        self,
        exc: Exception,
        category: str,
        *,
        action: str,
        recovered: bool,
        attempt: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        log_client_init_failure(
            exc=exc,
            category=category,
            action=action,
            recovered=recovered,
            configured=self._telegram_config_status(),
            attempt=attempt,
            extra=extra,
        )

    def _telethon_proxy(self, proxy_url: str | None):
        return telethon_proxy(proxy_url)

    def _socks_proxy_tuple(self, parsed, scheme: str):
        from app.services.adapters.telegram.session.client_proxy import socks_proxy_tuple

        return socks_proxy_tuple(parsed, scheme)

    async def is_authorized(self) -> bool:
        try:
            client = await self.client()
            return await asyncio.wait_for(client.is_user_authorized(), timeout=8)
        except Exception as exc:
            category = self._classify_client_error(exc)
            self._log_client_init_failure(
                exc,
                category,
                action="check-authorized",
                recovered=False,
            )
            return False
