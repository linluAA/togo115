from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from telethon import TelegramClient
from app.services.adapters.telegram.session.client import BusyTimeoutSQLiteSession, TelegramSessionClientMixin

from app.config import settings
from app.db import add_log, json_loads
from app.services.integration_state import get_setting, module_proxy


TELEGRAM_SESSION_BUSY_TIMEOUT_MS = 15000
TELEGRAM_SESSION_CONNECT_TIMEOUT_SECONDS = 15
TELEGRAM_CLIENT_CONNECT_RETRIES = 3
TELEGRAM_CLIENT_CONNECT_RETRY_DELAY_SECONDS = 0.35


class TelegramSessionConfigMixin(TelegramSessionClientMixin):
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
