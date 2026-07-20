from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.db import db, init_db, utc_now
from app.services.subscription.library.match import result_matches_missing_episodes
from app.services.subscription.search import tasks as search_tasks
from app.services.subscription.search.service import search_and_attach_resources
from app.services.types import SearchResult


class FirstSearchChainTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "first-search-chain.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def _insert_sub(self, title: str = "西游记") -> int:
        now = utc_now()
        with db() as conn:
            cur = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, tmdb_id, keywords, quality_rules, delivery_mode, target_path,
                     tmdb_total_count, tmdb_seasons, status, created_at, updated_at)
                VALUES (?, 'tv', 233, ?, '{}', '115', '/tv', 25, '[]', 'active', ?, ?)
                """,
                (title, f'["{title}"]', now, now),
            )
            return int(cur.lastrowid)

    def test_emby_snapshot_failed_does_not_block_haisou_115(self) -> None:
        subscription = {
            "title": "西游记",
            "media_type": "tv",
            "keywords": ["西游记"],
            "tmdb_total_count": 25,
            "emby_episode_keys": [],
            "emby_snapshot_failed": True,
        }
        result = SearchResult(
            title="西游记",
            url="https://115.com/s/swfsc2b36dh?password=z730",
            source="site_plugin:海搜 Haisou",
            context="西游记",
        )
        self.assertTrue(result_matches_missing_episodes(subscription, result))

    def test_haisou_115_bare_title_allowed_when_missing(self) -> None:
        subscription = {
            "title": "西游记",
            "media_type": "tv",
            "keywords": ["西游记"],
            "tmdb_total_count": 25,
            "emby_episode_keys": [],
        }
        result = SearchResult(
            title="西游记",
            url="https://115.com/s/swfsc2b36dh?password=z730",
            source="site_plugin:海搜 Haisou",
            context="西游记",
        )
        self.assertTrue(result_matches_missing_episodes(subscription, result))

    def test_magnet_bare_title_still_rejected(self) -> None:
        subscription = {
            "title": "西游记",
            "media_type": "tv",
            "keywords": ["西游记"],
            "tmdb_total_count": 25,
            "emby_episode_keys": [],
        }
        result = SearchResult(
            title="西游记",
            url="magnet:?xt=urn:btih:" + "a" * 40,
            source="site_plugin:test",
            context="西游记",
        )
        self.assertFalse(result_matches_missing_episodes(subscription, result))

    async def test_search_marks_last_checked_even_when_tg_delivers(self) -> None:
        sub_id = self._insert_sub()
        created = [{"resource_id": 1, "url": "https://115.com/s/x"}]
        with patch(
            "app.services.subscription.search.service.enrich_subscription_with_library",
            AsyncMock(return_value={"id": sub_id, "title": "西游记", "status": "active", "media_type": "tv"}),
        ), patch(
            "app.services.subscription.search.service.subscription_should_hide",
            return_value=False,
        ), patch(
            "app.services.subscription.search.service.subscription_needs_resource_search",
            return_value=True,
        ), patch(
            "app.services.subscription.search.service._search_telegram_first",
            AsyncMock(return_value=(created, [], {"created": 1})),
        ), patch(
            "app.services.subscription.search.service._deliver_created_resources",
            AsyncMock(return_value=True),
        ):
            out = await search_and_attach_resources(sub_id)
        self.assertEqual(out, created)
        with db() as conn:
            row = conn.execute("SELECT last_checked_at FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        self.assertTrue(row["last_checked_at"])

    async def test_search_marks_last_checked_on_empty_path(self) -> None:
        sub_id = self._insert_sub("野狗骨头")
        with patch(
            "app.services.subscription.search.service.enrich_subscription_with_library",
            AsyncMock(return_value={"id": sub_id, "title": "野狗骨头", "status": "active", "media_type": "tv"}),
        ), patch(
            "app.services.subscription.search.service.subscription_should_hide",
            return_value=False,
        ), patch(
            "app.services.subscription.search.service.subscription_needs_resource_search",
            return_value=True,
        ), patch(
            "app.services.subscription.search.service._search_telegram_first",
            AsyncMock(return_value=([], [], {})),
        ), patch(
            "app.services.subscription.search.service._search_fallback_when_needed",
            AsyncMock(return_value=[]),
        ):
            out = await search_and_attach_resources(sub_id)
        self.assertEqual(out, [])
        with db() as conn:
            row = conn.execute("SELECT last_checked_at FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        self.assertTrue(row["last_checked_at"])

    def test_stale_running_job_is_not_reused(self) -> None:
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        fake = {"id": 9, "status": "running", "heartbeat_at": old, "started_at": old, "updated_at": old, "created_at": old}
        with patch.object(search_tasks, "latest_job", return_value=fake), patch.object(
            search_tasks, "create_job", return_value=99
        ) as create_job, patch(
            "app.services.jobs.mark_job_failed"
        ) as mark_failed:
            result = search_tasks.schedule_subscription_search(7)
        self.assertEqual(result["job_id"], 99)
        self.assertFalse(result.get("reused"))
        create_job.assert_called_once()
        mark_failed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
