from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from app.db_core import _is_sqlite_locked, db, json_dumps, utc_now

LOG_PRUNE_INTERVAL = 200
DEBUG_LOG_THROTTLE_SECONDS = 1.5
_DEBUG_THROTTLED_SCOPES = {"telegram", "tg_bot", "subscription"}
TELEGRAM_BOT_API_TOKEN_RE = re.compile(r"(?i)(api\.telegram\.org/bot)(\d{6,}:[A-Za-z0-9_-]{20,})")
TELEGRAM_BOT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])\d{6,}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_])")
_log_insert_count = 0
_debug_log_last_seen: dict[tuple[str, str], float] = {}


def add_log(level: str, scope: str, message: str, payload: dict[str, Any] | None = None) -> None:
    global _log_insert_count
    if _should_throttle_debug_log(level, scope, message):
        return
    safe_message = sanitize_log_value(message)
    safe_payload = sanitize_log_value(payload) if payload else None
    try:
        with db() as conn:
            values = (level, scope, safe_message, json_dumps(safe_payload) if safe_payload else None, utc_now())
            try:
                conn.execute(
                    "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    values,
                )
            except sqlite3.OperationalError as exc:
                if "no such table: logs" not in str(exc):
                    raise
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        level TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        message TEXT NOT NULL,
                        payload TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_logs_created_at
                        ON logs(created_at);
                    """
                )
                conn.execute(
                    "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    values,
                )
            _log_insert_count += 1
            if _log_insert_count >= LOG_PRUNE_INTERVAL:
                conn.execute(
                    """
                    DELETE FROM logs
                    WHERE id NOT IN (
                        SELECT id FROM logs ORDER BY id DESC LIMIT 5000
                    )
                    """
                )
                _log_insert_count = 0
    except sqlite3.OperationalError as exc:
        if not _is_sqlite_locked(exc):
            raise
        print(f"drop log because sqlite is locked: {scope} {safe_message}")


def sanitize_log_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_log_text(value)
    if isinstance(value, dict):
        return {key: sanitize_log_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_log_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_log_value(item) for item in value)
    return value


def _sanitize_log_text(text: str) -> str:
    text = TELEGRAM_BOT_API_TOKEN_RE.sub(r"\1***", text)
    return TELEGRAM_BOT_TOKEN_RE.sub("***", text)


def _should_throttle_debug_log(level: str, scope: str, message: str) -> bool:
    if level != "debug" or scope not in _DEBUG_THROTTLED_SCOPES:
        return False
    now = time.monotonic()
    key = (scope, message)
    last_seen = _debug_log_last_seen.get(key, 0.0)
    _debug_log_last_seen[key] = now
    return now - last_seen < DEBUG_LOG_THROTTLE_SECONDS
