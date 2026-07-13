from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.db import init_db
from app.services.source_stats import _source_stats_key, list_source_stats, record_source_fetch, source_health_status


class SourceHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def test_source_degrades_after_recent_failure_margin(self) -> None:
        key = _source_stats_key("site_plugin", "slow")
        for _ in range(3):
            record_source_fetch(key, "slow", "site_plugin", False, error="timeout")

        status = source_health_status(key)

        assert status["degraded"] is True
        assert status["reason"] == "recent_failures"

    def test_source_degrades_after_slow_latency(self) -> None:
        key = _source_stats_key("site_plugin", "slow")
        record_source_fetch(key, "slow", "site_plugin", True, items=1, latency_ms=15000)

        status = source_health_status(key)

        assert status["degraded"] is True
        assert status["reason"] == "slow_source"

    def test_source_not_degraded_after_successful_fast_fetch(self) -> None:
        key = _source_stats_key("site_plugin", "ok")
        record_source_fetch(key, "ok", "site_plugin", True, items=1, latency_ms=500)

        assert source_health_status(key)["degraded"] is False

    def test_list_source_stats_includes_health_fields(self) -> None:
        key = _source_stats_key("site_plugin", "broken")
        for _ in range(3):
            record_source_fetch(key, "broken", "site_plugin", False, error="timeout")

        stats = list_source_stats()

        assert stats[0]["source_key"] == key
        assert stats[0]["degraded"] is True
        assert stats[0]["degrade_reason"] == "recent_failures"
        assert stats[0]["success_rate"] == 0
