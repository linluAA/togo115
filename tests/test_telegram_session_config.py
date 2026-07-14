from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.adapters.telegram.session.config import (
    TELEGRAM_SESSION_BUSY_TIMEOUT_MS,
    BusyTimeoutSQLiteSession,
    TelegramSessionConfigMixin,
)


class TelegramSessionConfigTest(unittest.TestCase):
    def test_telegram_session_enables_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = BusyTimeoutSQLiteSession(str(Path(tmp) / "telegram_user"))
            try:
                cursor = session._cursor()
                busy_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
                cursor.close()
            finally:
                session.close()

        self.assertEqual(busy_timeout, TELEGRAM_SESSION_BUSY_TIMEOUT_MS)
        self.assertEqual(str(journal_mode).casefold(), "wal")

    def test_client_init_lock_does_not_shadow_method(self) -> None:
        mixin = TelegramSessionConfigMixin()
        first = mixin._get_client_init_lock(object())
        second = mixin._get_client_init_lock(object())

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(callable(mixin._get_client_init_lock))

    def test_classifies_initialization_errors(self) -> None:
        mixin = TelegramSessionConfigMixin()

        cases = [
            (sqlite3.OperationalError("database is locked"), "session-locked"),
            (sqlite3.DatabaseError("file is not a database"), "session-corrupt"),
            (asyncio.TimeoutError(), "timeout"),
            (OSError("Connection refused by proxy"), "network-or-proxy"),
            (RuntimeError("Telegram API ID/API HASH 尚未配置"), "missing-config"),
            (RuntimeError("Auth key unregistered"), "auth"),
        ]

        for exc, category in cases:
            with self.subTest(category=category):
                self.assertEqual(mixin._classify_client_error(exc), category)

    def test_config_status_contains_session_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramSessionConfigMixin):
                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

            session_file = Path(tmp) / "telegram_user.session"
            session_file.write_text("session", encoding="utf-8")
            with patch("app.services.adapters.telegram.session.config.get_setting", return_value={"api_id": "1", "api_hash": "hash"}):
                status = LocalMixin()._telegram_config_status()

        self.assertEqual(status["api_id"], True)
        self.assertEqual(status["api_hash"], True)
        self.assertEqual(status["session_file"], True)
        self.assertTrue(str(status["session_path"]).endswith("telegram_user.session"))

    def test_quarantine_corrupt_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramSessionConfigMixin):
                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

            session_file = Path(tmp) / "telegram_user.session"
            wal_file = Path(str(session_file) + "-wal")
            session_file.write_text("broken", encoding="utf-8")
            wal_file.write_text("wal", encoding="utf-8")

            quarantined = LocalMixin()._quarantine_session_file()

            self.assertIsNotNone(quarantined)
            self.assertFalse(session_file.exists())
            self.assertTrue(Path(quarantined).exists())
            self.assertTrue(Path(str(quarantined) + "-wal").exists())

