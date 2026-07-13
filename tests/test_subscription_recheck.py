from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.db import db, init_db
from app.services.adapters.pan115 import SHARE_AVAILABLE, SHARE_UNAVAILABLE, SHARE_UNKNOWN
from app.services.subscription_recheck import list_due_recheck_resources, recheck_pending_115_resources


class FakePan115Adapter:
    state = SHARE_UNKNOWN

    async def share_availability(self, link: str) -> str:
        return self.state


class SubscriptionRecheckTest(unittest.IsolatedAsyncioTestCase):
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

    def _insert_recheck_resource(self, *, retry_count: int = 0, seconds_ago: int = 60) -> int:
        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(seconds=seconds_ago)).isoformat()
        with db() as conn:
            sub_id = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, delivery_mode, target_path, created_at, updated_at)
                VALUES
                    ('将夜', 'tv', '["将夜"]', '115', '/tv/将夜', ?, ?)
                """,
                (created_at, created_at),
            ).lastrowid
            resource_id = conn.execute(
                """
                INSERT INTO resources
                    (subscription_id, source, title, url, status, retry_count, last_error, created_at, updated_at)
                VALUES
                    (?, 'Telegram', '将夜 E01', 'https://115.com/s/abc?password=8888',
                     'pending_recheck', ?, '待复检', ?, ?)
                """,
                (sub_id, retry_count, created_at, created_at),
            ).lastrowid
        return int(resource_id)

    async def test_due_recheck_available_resource_is_delivered(self) -> None:
        resource_id = self._insert_recheck_resource()
        delivered: list[int] = []
        FakePan115Adapter.state = SHARE_AVAILABLE

        async def fake_deliver(item_id: int) -> bool:
            delivered.append(item_id)
            with db() as conn:
                conn.execute("UPDATE resources SET status = 'delivered' WHERE id = ?", (item_id,))
            return True

        result = await recheck_pending_115_resources(pan115_adapter_cls=FakePan115Adapter, deliver=fake_deliver)

        assert result["delivered"] == 1
        assert delivered == [resource_id]

    async def test_due_recheck_unavailable_resource_is_marked_invalid(self) -> None:
        resource_id = self._insert_recheck_resource()
        FakePan115Adapter.state = SHARE_UNAVAILABLE

        result = await recheck_pending_115_resources(pan115_adapter_cls=FakePan115Adapter)

        with db() as conn:
            row = conn.execute("SELECT status, last_error FROM resources WHERE id = ?", (resource_id,)).fetchone()
        assert result["invalid"] == 1
        assert row["status"] == "link_invalid"
        assert "失效" in row["last_error"]

    async def test_unknown_recheck_keeps_pending_until_retry_limit(self) -> None:
        resource_id = self._insert_recheck_resource(retry_count=1, seconds_ago=180)
        FakePan115Adapter.state = SHARE_UNKNOWN

        result = await recheck_pending_115_resources(pan115_adapter_cls=FakePan115Adapter)

        with db() as conn:
            row = conn.execute("SELECT status, retry_count FROM resources WHERE id = ?", (resource_id,)).fetchone()
        assert result["pending"] == 1
        assert row["status"] == "pending_recheck"
        assert row["retry_count"] == 2

    def test_recent_recheck_resource_is_not_due(self) -> None:
        self._insert_recheck_resource(seconds_ago=5)

        assert list_due_recheck_resources() == []
