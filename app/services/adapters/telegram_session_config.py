from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import socks
from telethon import TelegramClient
from telethon.sessions import SQLiteSession

from app.config import settings
from app.db import add_log, json_loads
from app.services.integration_state import get_setting, module_proxy


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


class _TelegramSessionConfigMixin:
    def _session_path(self) -> Path:
        return settings.data_dir / "telegram_user"

    def _session_file_path(self) -> Path:
        path = self._session_path()
        return path if path.suffix == ".session" else path.with_suffix(".session")

    def _config(self) -> dict[str, Any]:
        config = get_setting("telegram")
        if not config.get("api_id") or not config.get("api_hash"):
            raise RuntimeError("Telegram API ID/API HASH 尚未配置")
        return config

    def _configured_sources(self, config: dict[str, Any]) -> list[str]:
        raw_sources = self._raw_source_list(config.get("sources", ""))
        sources: list[str] = []
        seen: set[str] = set()
        for item in raw_sources:
            source = self._source_value(item)
            if source and source not in seen:
                seen.add(source)
                sources.append(source)
        return sources

    def _raw_source_list(self, value: Any) -> list[Any]:
        if isinstance(value, str):
            parsed = json_loads(value, None)
            return parsed if isinstance(parsed, list) else re.split(r"[,\n\r]+", value)
        return value if isinstance(value, list) else [value]

    def _source_value(self, item: Any) -> str:
        if isinstance(item, dict):
            value = item.get("source") or item.get("canonical") or item.get("id") or item.get("value") or item.get("username")
        else:
            value = item
        return str(value or "").strip().strip("[]'\" ")

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
                        {"category": self._classify_client_error(last_error) if last_error else "unknown", "attempt": attempt + 1, "action": "connect-recovered", "recovered": True},
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
        can_retry = attempt < TELEGRAM_CLIENT_CONNECT_RETRIES - 1 and category in {"session-locked", "timeout", "network-or-proxy"}
        action = "reset-client-and-retry" if category == "session-locked" else "retry-connect"
        if can_retry:
            if category == "session-locked":
                await self._reset_client_state()
            self._log_client_init_failure(exc, category, action=action, recovered=category == "session-locked", attempt=attempt + 1)
            await asyncio.sleep(TELEGRAM_CLIENT_CONNECT_RETRY_DELAY_SECONDS * (attempt + 1))
            return True
        self._log_client_init_failure(exc, category, action="raise", recovered=False, attempt=attempt + 1)
        return False

    async def _handle_corrupt_session(self, exc: Exception, attempt: int) -> None:
        quarantined = self._quarantine_session_file()
        await self._reset_client_state()
        self._log_client_init_failure(
            exc,
            "session-corrupt",
            action="quarantine-session-relogin",
            recovered=bool(quarantined),
            attempt=attempt + 1,
            extra={"quarantined_session": quarantined},
        )
        raise RuntimeError("Telegram 会话文件异常，已隔离旧会话，请重新登录 Telegram") from exc

    async def _reset_client_state(self) -> None:
        cls = type(self)
        listener_task = getattr(cls, "_listener_task", None)
        if listener_task and not listener_task.done():
            listener_task.cancel()
        client = getattr(cls, "_client", None)
        if client and client.is_connected():
            try:
                await client.disconnect()
            except Exception:
                pass
        cls._client = None
        cls._client_loop = None
        cls._listener_task = None
        cls._handler_registered = False
        cls._handler = None
        cls._handler_sources = ()

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
        text = f"{type(exc).__name__}: {exc!s} {exc!r}".casefold()
        if isinstance(exc, asyncio.TimeoutError) or "timeout" in text or "timed out" in text:
            return "timeout"
        if "api id/api hash" in text or "尚未配置" in text or "missing-config" in text:
            return "missing-config"
        if "database is locked" in text or "database table is locked" in text or "database locked" in text:
            return "session-locked"
        if (
            "file is not a database" in text
            or "database disk image is malformed" in text
            or "malformed" in text
            or "corrupt" in text
            or "no such table" in text
        ):
            return "session-corrupt"
        if (
            "auth key" in text
            or "unauthorized" in text
            or "session revoked" in text
            or "user deactivated" in text
            or "not logged in" in text
        ):
            return "auth"
        if (
            "proxy" in text
            or "socks" in text
            or "connection refused" in text
            or "connection reset" in text
            or "network" in text
            or "host unreachable" in text
            or "name or service not known" in text
            or "temporary failure" in text
            or "ssl" in text
            or "tls" in text
        ):
            return "network-or-proxy"
        return "unknown"

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
        payload: dict[str, Any] = {
            "category": category,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "error_repr": repr(exc),
            "configured": self._telegram_config_status(),
            "action": action,
            "recovered": recovered,
        }
        if attempt is not None:
            payload["attempt"] = attempt
        if extra:
            payload.update(extra)
        add_log("warning", "telegram", "Telegram 客户端初始化失败", payload)

    def _telethon_proxy(self, proxy_url: str | None):
        if not proxy_url:
            return None
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        if scheme.startswith("socks"):
            return self._socks_proxy_tuple(parsed, scheme)
        if scheme in ("http", "https"):
            return ("http", parsed.hostname, parsed.port, True, parsed.username, parsed.password)
        return None

    def _socks_proxy_tuple(self, parsed, scheme: str):
        try:
            import socks
        except ImportError as exc:
            raise RuntimeError("使用 socks 代理需要安装 PySocks") from exc
        proxy_type = socks.SOCKS5 if scheme == "socks5" else socks.SOCKS4
        return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password)

    async def is_authorized(self) -> bool:
        try:
            client = await self.client()
            return await asyncio.wait_for(client.is_user_authorized(), timeout=8)
        except Exception as exc:
            category = self._classify_client_error(exc)
            add_log(
                "warning",
                "telegram",
                "Telegram 客户端初始化失败",
                {
                    "category": category,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "error_repr": repr(exc),
                    "configured": self._telegram_config_status(),
                    "action": "check-authorized",
                    "recovered": False,
                },
            )
            return False

    def _telegram_config_status(self) -> dict[str, Any]:
        session_file = self._session_file_path()
        try:
            config = get_setting("telegram")
        except Exception:
            return {"api_id": False, "api_hash": False, "session_file": False, "session_path": str(session_file)}
        return {
            "api_id": bool(config.get("api_id")),
            "api_hash": bool(config.get("api_hash")),
            "session_file": session_file.exists(),
            "session_path": str(session_file),
        }
