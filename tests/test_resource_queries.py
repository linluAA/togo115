from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.db import db, init_db, utc_now
from app.services.resource_queries import clear_resources, delete_resources, list_recent_resources


class ResourceQueriesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-resource-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def _resource_ids(self) -> list[int]:
        now = utc_now()
        with db() as conn:
            sub = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path, created_at, updated_at)
                VALUES ('Drama', 'tv', '[]', '{}', '115', '/tv/Drama', ?, ?)
                """,
                (now, now),
            ).lastrowid
            ids = []
            for index in range(3):
                cursor = conn.execute(
                    """
                    INSERT INTO resources (subscription_id, source, title, url, status, created_at)
                    VALUES (?, 'telegram:test', ?, ?, 'pending', ?)
                    """,
                    (sub, f"Drama {index}", f"https://115.com/s/demo{index}?password=8888", now),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def test_delete_resources_removes_selected_rows_only(self) -> None:
        ids = self._resource_ids()

        deleted = delete_resources([ids[0], ids[2], ids[2]])
        remaining = list_recent_resources()

        self.assertEqual(deleted, 2)
        self.assertEqual([item["id"] for item in remaining], [ids[1]])

    def test_clear_resources_removes_all_rows(self) -> None:
        self._resource_ids()

        deleted = clear_resources()

        self.assertEqual(deleted, 3)
        self.assertEqual(list_recent_resources(), [])
