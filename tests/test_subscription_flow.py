import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.db import db, init_db, utc_now
from app.services.integrations import SearchResult, TelegramClientAdapter
from app.services import subscription_library_snapshot as snapshot_module
from app.services import subscription_runtime as runtime_module
from app.services import subscription_tasks
from app.services.subscription_search import search_and_attach_resources
from app.services.subscription_search_all import search_all_active_subscriptions
from app.services.subscription_matching import result_matches_subscription


class SubscriptionSearchFlowTest(unittest.IsolatedAsyncioTestCase):
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

    def _subscription(self) -> int:
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path, created_at, updated_at)
                VALUES
                    ('南部档案', 'tv', '["南部档案"]', '{}', '115', '/电视剧/南部档案', ?, ?)
                """,
                (now, now),
            )
            return int(cursor.lastrowid)

    def _drama_subscription(self) -> int:
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path,
                     tmdb_total_count, emby_episode_keys, created_at, updated_at)
                VALUES
                    ('Drama', 'tv', '["Drama"]', '{}', '115', '/tv/Drama',
                     10, '["1x1","1x2","1x3","1x4","1x5"]', ?, ?)
                """,
                (now, now),
            )
            return int(cursor.lastrowid)

    def _movie_subscription(self, title: str = "后室", year: int = 2026) -> int:
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, release_year, keywords, quality_rules, delivery_mode, target_path, created_at, updated_at)
                VALUES
                    (?, 'movie', ?, ?, '{}', '115', ?, ?, ?)
                """,
                (title, year, f'["{title}"]', f'/电影/{title}', now, now),
            )
            return int(cursor.lastrowid)

    async def test_movie_telegram_link_without_title_is_not_delivered(self) -> None:
        subscription_id = self._movie_subscription()
        telegram_result = SearchResult(
            title="Telegram 消息",
            url="https://115.com/s/backrooms?password=8888",
            source="-100123",
            context="资源链接：https://115.com/s/backrooms?password=8888",
        )

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter") as pan_cls, patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            pan_cls.return_value.share_availability = AsyncMock(return_value="available")
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(results, [])
        deliver.assert_not_awaited()
        rss_cls.return_value.search_history_by_priority_until_match.assert_awaited_once()
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM resources WHERE subscription_id = ?", (subscription_id,)).fetchone()["count"]
        self.assertEqual(count, 0)

    async def test_telegram_result_with_generic_title_uses_context_and_delivers(self) -> None:
        subscription_id = self._movie_subscription()
        telegram_result = SearchResult(
            title="Telegram 资源",
            url="https://115.com/s/backrooms?password=8888",
            source="telegram:test",
            context="电影：后室 2026\n链接：https://115.com/s/backrooms?password=8888",
        )

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://115.com/s/backrooms?password=8888")
        deliver.assert_awaited_once()
        rss_cls.return_value.search_history_by_priority_until_match.assert_not_awaited()

    async def test_bad_telegram_result_does_not_block_source_fallback(self) -> None:
        subscription_id = self._subscription()
        bad_title = object()
        telegram_result = SearchResult(
            title=bad_title,  # type: ignore[arg-type]
            url="https://115.com/s/bad?password=0000",
            source="telegram:test",
            context="",
        )
        rss = AsyncMock(return_value=[])

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch("app.services.subscription_discovery.RssTorznabAdapter") as rss_cls:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = rss

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(results, [])
        rss.assert_awaited_once()

    async def test_telegram_115_link_without_episode_text_is_saved_before_fallback(self) -> None:
        subscription_id = self._drama_subscription()
        telegram_result = SearchResult(
            title="Drama 1080p",
            url="https://115.com/s/dramacode?password=8888",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/dramacode?password=8888",
        )

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(len(results), 1)
        deliver.assert_awaited_once()
        rss_cls.return_value.search_history_by_priority_until_match.assert_not_awaited()

    async def test_owned_telegram_episode_is_not_saved_or_delivered(self) -> None:
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path,
                     tmdb_total_count, emby_count, emby_episode_keys, created_at, updated_at)
                VALUES
                    ('野狗骨头', 'tv', '["野狗骨头"]', '{}', '115', '/tv/野狗骨头',
                     32, 11, ?, ?, ?)
                """,
                (str([f"1x{episode}" for episode in range(1, 12)]).replace("'", '"'), now, now),
            )
            subscription_id = int(cursor.lastrowid)
        telegram_result = SearchResult(
            title="野狗骨头.2026.S01E01.第1集.2160p.WEB-DL.H.265.AAC.mp4",
            url="https://115.com/s/wilddog01?password=8888",
            source="-100123",
            context="野狗骨头.2026.S01E01.第1集.2160p.WEB-DL.H.265.AAC.mp4\nhttps://115.com/s/wilddog01?password=8888",
        )

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter") as pan_cls, patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            pan_cls.return_value.share_availability = AsyncMock(return_value="available")
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(results, [])
        deliver.assert_not_awaited()
        with db() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM resources WHERE subscription_id = ?", (subscription_id,)).fetchone()["count"]
        self.assertEqual(count, 0)

    async def test_delivery_skips_stale_resource_for_owned_episode(self) -> None:
        from app.services.subscription_delivery import deliver_resource

        subscription_id = self._drama_subscription()
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO resources (subscription_id, source, title, url, message_id, created_at, updated_at)
                VALUES (?, '-100123', 'Drama S01E01 1080p', 'https://115.com/s/drama01?password=8888', '1', ?, ?)
                """,
                (subscription_id, now, now),
            )
            resource_id = int(cursor.lastrowid)

        with patch("app.services.subscription_delivery._deliver_resource_url", AsyncMock(return_value=(True, ""))) as deliver_url:
            ok = await deliver_resource(resource_id)

        self.assertFalse(ok)
        deliver_url.assert_not_awaited()
        with db() as conn:
            row = conn.execute("SELECT status, last_error FROM resources WHERE id = ?", (resource_id,)).fetchone()
        self.assertEqual(row["status"], "skipped")
        self.assertIn("缺失范围", row["last_error"])

    async def test_search_waits_for_created_resource_delivery(self) -> None:
        subscription_id = self._drama_subscription()
        telegram_result = SearchResult(
            title="Drama 1080p",
            url="https://115.com/s/dramacode?password=8888",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/dramacode?password=8888",
        )
        started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def slow_deliver(resource_id: int) -> bool:
            started.set()
            await allow_finish.wait()
            return True

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_search.deliver_resource", AsyncMock(side_effect=slow_deliver)):
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            task = asyncio.create_task(search_and_attach_resources(subscription_id))
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0)

            self.assertFalse(task.done())
            allow_finish.set()
            results = await task

        self.assertEqual(len(results), 1)

    async def test_expired_115_link_is_skipped_and_next_link_is_delivered(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        expired = SearchResult(
            title="Drama 1080p expired",
            url="https://115.com/s/expired?password=1111",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/expired?password=1111",
        )
        valid = SearchResult(
            title="Drama 1080p valid",
            url="https://115.com/s/valid?password=2222",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/valid?password=2222",
        )
        pan = AsyncMock()
        pan.share_availability = AsyncMock(side_effect=["unavailable", "available"])

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[expired, valid])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://115.com/s/valid?password=2222")
        deliver.assert_awaited_once()
        with db() as conn:
            rows = conn.execute("SELECT url FROM resources ORDER BY id").fetchall()
        self.assertEqual([row["url"] for row in rows], ["https://115.com/s/valid?password=2222"])

    async def test_multiple_valid_telegram_hits_only_deliver_best_candidate(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        lower = SearchResult(
            title="Drama S01E06 720p",
            url="https://115.com/s/lower?password=1111",
            source="-100123",
            context="Drama S01E06 720p\nTMDB ID: 12345\nhttps://115.com/s/lower?password=1111",
            priority=1,
        )
        better = SearchResult(
            title="Drama S01E06 1080p",
            url="https://115.com/s/better?password=2222",
            source="-100123",
            context="Drama S01E06 1080p\nTMDB ID: 12345\nhttps://115.com/s/better?password=2222",
            priority=20,
        )
        pan = AsyncMock()
        pan.share_availability = AsyncMock(return_value="available")

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[lower, better])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual([item["url"] for item in results], ["https://115.com/s/better?password=2222"])
        deliver.assert_awaited_once()
        rss_cls.return_value.search_history_by_priority_until_match.assert_not_awaited()
        with db() as conn:
            rows = conn.execute("SELECT url FROM resources ORDER BY id").fetchall()
        self.assertEqual([row["url"] for row in rows], ["https://115.com/s/better?password=2222"])

    async def test_duplicate_telegram_resource_does_not_trigger_magnet_fallback(self) -> None:
        subscription_id = self._drama_subscription()
        url = "https://115.com/s/dramacode?password=8888"
        now = utc_now()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))
            conn.execute(
                """
                INSERT INTO resources (subscription_id, source, title, url, status, created_at, updated_at)
                VALUES (?, 'telegram:test', 'Drama S01E06 1080p', ?, 'delivered', ?, ?)
                """,
                (subscription_id, url, now, now),
            )
        telegram_result = SearchResult(
            title="Drama S01E06 1080p",
            url=url,
            source="-100123",
            context="Drama S01E06 1080p\nTMDB ID: 12345\nhttps://115.com/s/dramacode?password=8888",
        )
        pan = AsyncMock()
        pan.share_availability = AsyncMock(return_value="available")

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(results, [])
        deliver.assert_not_awaited()
        rss_cls.return_value.search_history_by_priority_until_match.assert_not_awaited()

    async def test_unknown_telegram_115_link_is_saved_for_recheck_and_falls_back(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        recheck = SearchResult(
            title="Drama S01E06 1080p recheck",
            url="https://115.com/s/recheck?password=1111",
            source="-100123",
            context="Drama S01E06 1080p\nTMDB ID: 12345\nhttps://115.com/s/recheck?password=1111",
        )
        pan = AsyncMock()
        pan.share_availability = AsyncMock(return_value="unknown")

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[recheck])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=[])

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://115.com/s/recheck?password=1111")
        deliver.assert_awaited_once()
        rss_cls.return_value.search_history_by_priority_until_match.assert_not_awaited()
        with db() as conn:
            rows = conn.execute("SELECT url FROM resources ORDER BY id").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://115.com/s/recheck?password=1111")

    async def test_expired_telegram_115_link_falls_back_to_magnet_source(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        expired = SearchResult(
            title="Drama 1080p expired",
            url="https://115.com/s/expired?password=1111",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/expired?password=1111",
        )
        magnet = SearchResult(
            title="Drama S01E06 1080p magnet",
            url="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            source="site_plugin:test",
            context="Drama S01E06 1080p magnet\nTMDB ID: 12345",
        )
        pan = AsyncMock()
        pan.share_availability = AsyncMock(return_value="unavailable")
        fallback_groups = [
            {
                "priority": 1,
                "source": {"name": "test-magnet", "type": "site_plugin"},
                "results": [magnet],
            }
        ]

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(return_value=True)
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[expired])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=fallback_groups)

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], magnet.url)
        deliver.assert_awaited_once()
        rss_cls.return_value.search_history_by_priority_until_match.assert_awaited_once()
        with db() as conn:
            rows = conn.execute("SELECT url FROM resources ORDER BY id").fetchall()
        self.assertEqual([row["url"] for row in rows], [magnet.url])

    async def test_telegram_delivery_failure_falls_back_to_magnet_source(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        telegram_result = SearchResult(
            title="Drama S01E06 1080p",
            url="https://115.com/s/dramacode?password=8888",
            source="-100123",
            context="Drama S01E06 1080p\nTMDB ID: 12345\nhttps://115.com/s/dramacode?password=8888",
        )
        magnet = SearchResult(
            title="Drama S01E06 1080p magnet",
            url="magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc",
            source="site_plugin:test",
            context="Drama S01E06 1080p magnet\nTMDB ID: 12345",
        )
        fallback_groups = [
            {
                "priority": 1,
                "source": {"name": "test-magnet", "type": "site_plugin"},
                "results": [magnet],
            }
        ]
        pan = AsyncMock()
        pan.share_availability = AsyncMock(return_value="available")

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_link_validation.Pan115Adapter", return_value=pan), patch(
            "app.services.subscription_search.deliver_resource", AsyncMock(side_effect=[False, True])
        ) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[telegram_result])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=fallback_groups)

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual([item["url"] for item in results], [telegram_result.url, magnet.url])
        self.assertEqual(deliver.await_count, 2)
        rss_cls.return_value.search_history_by_priority_until_match.assert_awaited_once()

    async def test_failed_magnet_delivery_tries_next_candidate(self) -> None:
        subscription_id = self._drama_subscription()
        with db() as conn:
            conn.execute("UPDATE subscriptions SET tmdb_id = ? WHERE id = ?", (12345, subscription_id))

        first = SearchResult(
            title="Drama S01E06 1080p candidate A",
            url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source="site_plugin:test",
            context="Drama S01E06 1080p\nTMDB ID: 12345",
            priority=10,
        )
        second = SearchResult(
            title="Drama S01E06 1080p candidate B",
            url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            source="site_plugin:test",
            context="Drama S01E06 1080p\nTMDB ID: 12345",
            priority=9,
        )
        fallback_groups = [
            {
                "priority": 1,
                "source": {"name": "test-magnet", "type": "site_plugin"},
                "results": [first, second],
            }
        ]

        with patch("app.services.subscription_discovery.TelegramClientAdapter") as telegram_cls, patch(
            "app.services.subscription_discovery.RssTorznabAdapter"
        ) as rss_cls, patch("app.services.subscription_search.deliver_resource", AsyncMock(side_effect=[False, True])) as deliver:
            telegram_cls.return_value.search_history = AsyncMock(return_value=[])
            rss_cls.return_value.search_history_by_priority_until_match = AsyncMock(return_value=fallback_groups)

            results = await search_and_attach_resources(subscription_id)

        self.assertEqual([item["url"] for item in results], [first.url, second.url])
        self.assertEqual(deliver.await_count, 2)
        with db() as conn:
            rows = conn.execute("SELECT url, status FROM resources ORDER BY id").fetchall()
        self.assertEqual([row["url"] for row in rows], [first.url, second.url])
        self.assertEqual(rows[0]["status"], "skipped")

    def test_pan115_share_payload_recognizes_chinese_expired_messages(self) -> None:
        from app.services.adapters.pan115 import Pan115Adapter

        adapter = Pan115Adapter()
        self.assertFalse(adapter._share_available_payload({"state": False, "error": "\u5206\u4eab\u5df2\u53d6\u6d88"}))
        self.assertFalse(adapter._share_available_payload({"state": False, "message": "\u6587\u4ef6\u4e0d\u5b58\u5728\u6216\u5df2\u8fc7\u671f"}))
        self.assertFalse(adapter._share_available_payload({"state": False, "msg": "\u63d0\u53d6\u7801\u9519\u8bef"}))
        self.assertTrue(adapter._share_available_payload({"state": True}))

    async def test_tmdb_id_match_overrides_stale_subscription_year(self) -> None:
        subscription = {
            "id": 26,
            "title": "气体人第一号",
            "media_type": "tv",
            "tmdb_id": 253960,
            "release_year": 2025,
            "keywords": ["气体人第一号"],
            "quality_rules": {},
            "tmdb_total_count": 8,
            "tmdb_seasons": [],
            "emby_episode_keys": [],
        }
        result = SearchResult(
            title="电视剧：气体人第一号（2026）更新至8集 1080P",
            url="https://115.com/s/swss2do3nbi?password=8888",
            source="-1003793333793",
            context="电视剧：气体人第一号（2026）- S01E01-E08(完结)\nTMDB ID: 253960\n质量：WEB-DL 2160p",
        )

        self.assertTrue(result_matches_subscription(subscription, result))


    def test_update_to_pack_already_in_library_does_not_match_missing_episodes(self) -> None:
        subscription = {
            "id": 29,
            "title": "\u91ce\u72d7\u9aa8\u5934",
            "media_type": "tv",
            "tmdb_total_count": 32,
            "emby_count": 8,
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 9)],
            "keywords": ["\u91ce\u72d7\u9aa8\u5934"],
        }
        result = SearchResult(
            title="[yiyidj.org] \u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f306\u96c6[4K1080P][\u5267\u60c5\u7231\u60c5]",
            url="magnet:?xt=urn:btih:" + "a" * 40,
            source="site_plugin:BT1207",
            context="[yiyidj.org] \u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f306\u96c6[4K1080P][\u5267\u60c5\u7231\u60c5]",
        )

        self.assertTrue(result_matches_subscription(subscription, result))
        from app.services.subscription_library_match import result_matches_missing_episodes

        self.assertFalse(result_matches_missing_episodes(subscription, result))

    def test_update_to_pack_with_missing_episode_matches(self) -> None:
        subscription = {
            "id": 29,
            "title": "\u91ce\u72d7\u9aa8\u5934",
            "media_type": "tv",
            "tmdb_total_count": 32,
            "emby_count": 8,
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 9)],
            "keywords": ["\u91ce\u72d7\u9aa8\u5934"],
        }
        result = SearchResult(
            title="\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f312\u96c6 1080P",
            url="magnet:?xt=urn:btih:" + "b" * 40,
            source="site_plugin:BT1207",
            context="\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f312\u96c6 1080P",
        )

        self.assertTrue(result_matches_subscription(subscription, result))
        from app.services.subscription_library_match import result_matches_missing_episodes

        self.assertTrue(result_matches_missing_episodes(subscription, result))

    async def test_telegram_cursor_keeps_highest_message_id(self) -> None:
        adapter = TelegramClientAdapter()
        adapter._update_telegram_cursor("dialog-a", 12)
        adapter._update_telegram_cursor("dialog-a", 8)
        adapter._update_telegram_cursor("dialog-a", 18)

        self.assertEqual(adapter._telegram_cursor("dialog-a"), 18)

    async def test_emby_snapshot_cache_is_reused(self) -> None:
        snapshot_module.reset_library_snapshot_cache()
        snapshot = {"movies": [], "series": [], "episodes": []}

        with patch("app.services.subscription_library_snapshot._emby_configured", return_value=True), patch("app.services.subscription_library_snapshot.EmbyAdapter") as emby_cls:
            emby_cls.return_value.library_snapshot = AsyncMock(return_value=snapshot)
            first = await snapshot_module._library_snapshot_or_none()
            second = await snapshot_module._library_snapshot_or_none()

        self.assertIs(first, snapshot)
        self.assertIs(second, snapshot)
        emby_cls.return_value.library_snapshot.assert_awaited_once()

    async def test_search_all_writes_visible_summary_logs(self) -> None:
        self._subscription()

        search_mock = AsyncMock(return_value=[])
        with patch("app.services.subscription_search_all._library_snapshot_or_none", AsyncMock(return_value=None)), patch(
            "app.services.subscription_search_all._search_and_attach_resources_guarded", search_mock
        ):
            result = await search_all_active_subscriptions()

        self.assertEqual(search_mock.await_args.kwargs.get("incremental_telegram"), False)
        self.assertEqual(result["searched"], 1)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["failed"], 0)
        with db() as conn:
            rows = conn.execute("SELECT level, message FROM logs WHERE scope = 'subscription' ORDER BY id").fetchall()
        messages = [row["message"] for row in rows if row["level"] == "info"]
        self.assertIn("搜索全部活跃订阅开始", messages)
        self.assertIn("搜索全部活跃订阅完成", messages)

    async def test_search_all_times_out_stuck_subscription_search(self) -> None:
        self._subscription()

        async def stuck_search(*args, **kwargs):
            await asyncio.sleep(0.2)

        with patch("app.services.subscription_search_all._library_snapshot_or_none", AsyncMock(return_value=None)), patch(
            "app.services.subscription_search_all._search_and_attach_resources_guarded", AsyncMock(side_effect=stuck_search)
        ), patch.object(runtime_module, "SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS", 0.01):
            result = await search_all_active_subscriptions()

        self.assertEqual(result["searched"], 1)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["failed"], 1)
        with db() as conn:
            row = conn.execute("SELECT message FROM logs WHERE level = 'error' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["message"], "\u641c\u7d22\u8ba2\u9605\u8d85\u65f6\uff0c\u5df2\u7ee7\u7eed\u5904\u7406\u4e0b\u4e00\u4e2a\u8ba2\u9605")

    async def test_background_subscription_searches_are_limited(self) -> None:
        first_id = self._subscription()
        second_id = self._drama_subscription()
        active = 0
        max_active = 0

        async def tracked_search(*args, **kwargs):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.03)
            active -= 1
            return []

        with patch("app.services.subscription_tasks._default_search", AsyncMock(side_effect=tracked_search)):
            await asyncio.gather(
                subscription_tasks._search_subscription_background(first_id, search_func=subscription_tasks._default_search),
                subscription_tasks._search_subscription_background(second_id, search_func=subscription_tasks._default_search),
            )

        self.assertEqual(max_active, runtime_module.SUBSCRIPTION_SEARCH_CONCURRENCY)

    async def test_same_subscription_search_is_not_run_twice_concurrently(self) -> None:
        subscription_id = self._subscription()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def tracked_search(*args, **kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return [{"resource_id": 1}]

        first = asyncio.create_task(
            subscription_tasks._search_and_attach_resources_guarded(subscription_id, search_func=tracked_search)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        second = await subscription_tasks._search_and_attach_resources_guarded(subscription_id, search_func=tracked_search)
        release.set()
        first_result = await first

        self.assertEqual(first_result, [{"resource_id": 1}])
        self.assertEqual(second, [])
        self.assertEqual(calls, 1)
        with db() as conn:
            row = conn.execute("SELECT message FROM logs WHERE scope = 'subscription' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["message"], "\u8ba2\u9605\u641c\u7d22\u5df2\u5728\u8fd0\u884c\uff0c\u5df2\u8df3\u8fc7\u91cd\u590d\u89e6\u53d1")

    async def test_scheduled_search_all_runs_as_async_background_task(self) -> None:
        async def nonblocking_search_all():
            await asyncio.sleep(0.08)
            return {"ok": True}

        old_task = runtime_module.search_all_task
        runtime_module.search_all_task = None
        try:
            with patch.object(runtime_module, "SEARCH_ALL_START_DELAY_SECONDS", 0), patch(
                "app.services.subscription_tasks._default_search_all",
                nonblocking_search_all,
            ):
                started = time.perf_counter()
                result = subscription_tasks.schedule_search_all_active_subscriptions()
                await asyncio.sleep(0.01)
                elapsed = time.perf_counter() - started
                task = runtime_module.search_all_task

            self.assertTrue(result["running"])
            self.assertLess(elapsed, 0.05)
            if task:
                await asyncio.wait_for(task, timeout=1)
        finally:
            runtime_module.search_all_task = old_task

    async def test_scheduled_subscription_search_runs_outside_api_event_loop(self) -> None:
        subscription_id = self._subscription()

        async def blocking_search(*args, **kwargs):
            time.sleep(0.08)
            return []

        old_task = runtime_module.subscription_search_tasks.get(subscription_id)
        runtime_module.subscription_search_tasks.pop(subscription_id, None)
        try:
            with patch("app.services.subscription_tasks._default_search", AsyncMock(side_effect=blocking_search)):
                started = time.perf_counter()
                result = subscription_tasks.schedule_subscription_search(subscription_id)
                await asyncio.sleep(0.01)
                elapsed = time.perf_counter() - started
                task = runtime_module.subscription_search_tasks.get(subscription_id)

                self.assertTrue(result["running"])
                self.assertLess(elapsed, 0.05)
                if task:
                    await asyncio.wait_for(task, timeout=1)
        finally:
            if old_task is not None:
                runtime_module.subscription_search_tasks[subscription_id] = old_task

    async def test_scheduled_search_all_runs_outside_api_event_loop_when_worker_blocks(self) -> None:
        async def blocking_search_all():
            time.sleep(0.08)
            return {"ok": True}

        old_task = runtime_module.search_all_task
        runtime_module.search_all_task = None
        try:
            with patch.object(runtime_module, "SEARCH_ALL_START_DELAY_SECONDS", 0), patch(
                "app.services.subscription_tasks._default_search_all",
                blocking_search_all,
            ):
                started = time.perf_counter()
                result = subscription_tasks.schedule_search_all_active_subscriptions()
                await asyncio.sleep(0.01)
                elapsed = time.perf_counter() - started
                task = runtime_module.search_all_task

                self.assertTrue(result["running"])
                self.assertLess(elapsed, 0.05)
                if task:
                    await asyncio.wait_for(task, timeout=1)
        finally:
            runtime_module.search_all_task = old_task

    async def test_scheduled_emby_sync_runs_outside_api_event_loop_when_worker_blocks(self) -> None:
        async def blocking_emby_sync():
            time.sleep(0.08)
            return {"ok": True}

        old_task = runtime_module.emby_sync_task
        runtime_module.emby_sync_task = None
        try:
            with patch.object(runtime_module, "EMBY_SYNC_START_DELAY_SECONDS", 0), patch(
                "app.services.subscription_tasks._default_emby_sync",
                blocking_emby_sync,
            ):
                started = time.perf_counter()
                result = subscription_tasks.schedule_emby_subscription_sync()
                await asyncio.sleep(0.01)
                elapsed = time.perf_counter() - started
                task = runtime_module.emby_sync_task

                self.assertTrue(result["running"])
                self.assertLess(elapsed, 0.05)
                if task:
                    await asyncio.wait_for(task, timeout=1)
        finally:
            runtime_module.emby_sync_task = old_task

    async def test_scheduled_emby_sync_skips_duplicate_trigger(self) -> None:
        started = threading.Event()
        release = threading.Event()

        async def slow_emby_sync():
            started.set()
            await asyncio.to_thread(release.wait)
            return {"ok": True}

        old_task = runtime_module.emby_sync_task
        runtime_module.emby_sync_task = None
        try:
            with patch.object(runtime_module, "EMBY_SYNC_START_DELAY_SECONDS", 0), patch(
                "app.services.subscription_tasks._default_emby_sync",
                slow_emby_sync,
            ):
                first = subscription_tasks.schedule_emby_subscription_sync()
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                second = subscription_tasks.schedule_emby_subscription_sync()
                release.set()
                task = runtime_module.emby_sync_task

                self.assertTrue(first["queued"])
                self.assertFalse(second["queued"])
                self.assertTrue(second["running"])
                if task:
                    await asyncio.wait_for(task, timeout=1)
        finally:
            runtime_module.emby_sync_task = old_task


if __name__ == "__main__":
    unittest.main()
