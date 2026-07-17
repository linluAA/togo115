from __future__ import annotations

import atexit
import re
import sqlite3
import threading
import time
from typing import Any

from app.db_core import _is_sqlite_locked, db, json_dumps, utc_now

LOG_PRUNE_INTERVAL = 200
DEBUG_LOG_THROTTLE_SECONDS = 1.5
LOG_BATCH_FLUSH_COUNT = 12
LOG_BATCH_FLUSH_SECONDS = 0.35
_DEBUG_THROTTLED_SCOPES = {"telegram", "tg_bot", "subscription"}
TELEGRAM_BOT_API_TOKEN_RE = re.compile(r"(?i)(api\.telegram\.org/bot)(\d{6,}:[A-Za-z0-9_-]{20,})")
TELEGRAM_BOT_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])\d{6,}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_])")
_log_insert_count = 0
_debug_log_last_seen: dict[tuple[str, str], float] = {}
_log_buffer: list[tuple[str, str, str, str | None, str]] = []
_log_buffer_lock = threading.Lock()
_log_buffer_last_flush = 0.0
# Always flush these immediately so operators still see critical events.
_IMMEDIATE_LEVELS = {"error", "warning"}
_IMMEDIATE_SCOPES = {"auth", "system"}


def add_log(level: str, scope: str, message: str, payload: dict[str, Any] | None = None) -> None:
    if _should_throttle_debug_log(level, scope, message):
        return
    safe_message = sanitize_log_value(message)
    safe_payload = sanitize_log_value(payload) if payload else None
    values = (
        str(level or "info"),
        str(scope or "app"),
        str(safe_message or ""),
        json_dumps(safe_payload) if safe_payload else None,
        utc_now(),
    )
    # Batch only debug chatter; info+ stays immediately queryable for operators/tests.
    if str(level or "").casefold() != "debug":
        _flush_log_rows([values], force_prune=True)
        return
    should_flush = False
    with _log_buffer_lock:
        _log_buffer.append(values)
        now = time.monotonic()
        global _log_buffer_last_flush
        if len(_log_buffer) >= LOG_BATCH_FLUSH_COUNT or (now - _log_buffer_last_flush) >= LOG_BATCH_FLUSH_SECONDS:
            should_flush = True
    if should_flush:
        flush_log_buffer()


def flush_log_buffer() -> None:
    with _log_buffer_lock:
        if not _log_buffer:
            return
        rows = list(_log_buffer)
        _log_buffer.clear()
        global _log_buffer_last_flush
        _log_buffer_last_flush = time.monotonic()
    _flush_log_rows(rows, force_prune=False)


def _flush_log_rows(rows: list[tuple[str, str, str, str | None, str]], *, force_prune: bool) -> None:
    global _log_insert_count
    if not rows:
        return
    try:
        with db() as conn:
            try:
                conn.executemany(
                    "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    rows,
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
                conn.executemany(
                    "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
            _log_insert_count += len(rows)
            if force_prune or _log_insert_count >= LOG_PRUNE_INTERVAL:
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
        print(f"drop log batch because sqlite is locked: {len(rows)} rows")


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


atexit.register(flush_log_buffer)
