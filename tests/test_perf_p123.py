from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.sources.haisou.budget import (
    allow_haisou_search,
    get_cached_haisou_search,
    haisou_budget_snapshot,
    note_haisou_search,
    reset_haisou_budget_for_tests,
    search_cache_key,
    set_cached_haisou_search,
)
from app.services.subscription.search.schedule import (
    filter_subscriptions_for_search_all,
    prioritize_subscriptions_for_search,
    should_skip_recent_complete_check,
)


class SubscriptionSearchScheduleTest(unittest.TestCase):
    def test_prioritize_missing_episodes_first(self) -> None:
        subs = [
            {
                "id": 1,
                "media_type": "tv",
                "tmdb_total_count": 10,
                "tmdb_seasons": [{"season_number": 1, "episode_count": 10}],
                "emby_episode_keys": [f"1x{i}" for i in range(1, 10)],
                "last_checked_at": "2026-07-20T10:00:00+00:00",
            },
            {
                "id": 2,
                "media_type": "tv",
                "tmdb_total_count": 10,
                "tmdb_seasons": [{"season_number": 1, "episode_count": 10}],
                "emby_episode_keys": [f"1x{i}" for i in range(1, 6)],
                "last_checked_at": "2026-07-20T11:00:00+00:00",
            },
            {
                "id": 3,
                "media_type": "movie",
                "in_library": True,
                "last_checked_at": "2026-07-20T09:00:00+00:00",
            },
        ]
        ordered = prioritize_subscriptions_for_search(subs)
        self.assertEqual([item["id"] for item in ordered], [2, 1, 3])

    def test_skip_recent_complete_tv(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        sub = {
            "id": 9,
            "media_type": "tv",
            "status": "active",
            "tmdb_total_count": 5,
            "tmdb_seasons": [{"season_number": 1, "episode_count": 5}],
            "emby_episode_keys": [f"1x{i}" for i in range(1, 6)],
            "last_checked_at": now,
        }
        self.assertTrue(should_skip_recent_complete_check(sub))
        kept, skipped = filter_subscriptions_for_search_all([sub])
        self.assertEqual(skipped, 1)
        self.assertEqual(kept, [])


class HaisouBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_haisou_budget_for_tests()

    def test_search_budget_and_cache(self) -> None:
        self.assertTrue(allow_haisou_search())
        key = search_cache_key("斗罗大陆", platforms=["115"], page_size=5, search_in="title")
        set_cached_haisou_search(key, [{"title": "x"}])
        cached = get_cached_haisou_search(key)
        self.assertEqual(cached, [{"title": "x"}])
        note_haisou_search()
        snap = haisou_budget_snapshot()
        self.assertGreaterEqual(int(snap["search_calls"]), 1)


class ActiveSearchCooldownTest(unittest.TestCase):
    def test_skip_recent_active_missing(self) -> None:
        from datetime import datetime, timezone
        from app.services.subscription.search.schedule import (
            SEARCH_ALL_ACTIVE_COOLDOWN_SECONDS,
            should_skip_recent_search_all,
        )

        now = datetime.now(timezone.utc).isoformat()
        sub = {
            "id": 11,
            "media_type": "tv",
            "tmdb_total_count": 10,
            "tmdb_seasons": [{"season_number": 1, "episode_count": 10}],
            "emby_episode_keys": ["1x1"],
            "last_checked_at": now,
        }
        self.assertTrue(should_skip_recent_search_all(sub))
        self.assertGreaterEqual(SEARCH_ALL_ACTIVE_COOLDOWN_SECONDS, 60)


class SourceHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.source_health import clear_source_health
        clear_source_health()

    def tearDown(self) -> None:
        from app.services.source_health import clear_source_health
        clear_source_health()

    def test_cooldown_after_failures(self) -> None:
        from app.services.source_health import (
            filter_ready_sources,
            note_source_failure,
            source_on_cooldown,
        )

        source = {"name": "slow-source", "url": "https://example.com"}
        note_source_failure(source, timeout=True)
        self.assertTrue(source_on_cooldown(source))
        ready = filter_ready_sources([source, {"name": "ok"}])
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["name"], "ok")


class FallbackUnblockTest(unittest.TestCase):
    def test_unlabeled_primary_does_not_block_labeled_pack(self) -> None:
        import sqlite3
        from app.services.subscription.resource.fallback import fallback_blocked_by_primary_resource
        from app.services.types import SearchResult

        conn = sqlite3.connect(":memory:")
        subscription = {"id": 1, "media_type": "tv", "title": "Drama", "tmdb_total_count": 10, "tmdb_seasons": [{"season_number": 1, "episode_count": 10}]}
        existing = [{"title": "Drama", "url": "https://115.com/s/a", "status": "delivered"}]
        pack = SearchResult(
            title="Drama 全10集",
            url="https://115.com/s/b?password=1",
            source="site_plugin:海搜",
            context="Drama 全10集",
        )
        self.assertFalse(fallback_blocked_by_primary_resource(conn, subscription, pack, existing))


class EmbyEpisodeIndexTest(unittest.TestCase):
    def test_index_snapshot_episodes(self) -> None:
        from app.services.subscription.library.snapshot import index_snapshot_episodes

        snap = {
            "movies": [],
            "series": [],
            "episodes": [
                {"SeriesId": "s1", "ParentIndexNumber": 1, "IndexNumber": 1},
                {"SeriesId": "s1", "ParentIndexNumber": 1, "IndexNumber": 2},
                {"SeriesId": "s2", "ParentIndexNumber": 1, "IndexNumber": 1},
            ],
        }
        indexed = index_snapshot_episodes(snap)
        self.assertEqual(len(indexed["_episodes_by_series"]["s1"]), 2)
        self.assertEqual(len(indexed["_episodes_by_series"]["s2"]), 1)


if __name__ == "__main__":
    unittest.main()