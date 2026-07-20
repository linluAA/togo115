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
from app.services.subscription.delivery.link_validation import _share_probe_plan
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


class ShareProbePlanTest(unittest.TestCase):
    def test_same_share_code_collapsed(self) -> None:
        urls = [
            "https://115.com/s/abc123?password=11",
            "https://www.115.com/s/abc123?password=11",
            "https://115.com/s/xyz999?password=22",
        ]
        reps, mapping = _share_probe_plan(urls)
        self.assertEqual(len(reps), 2)
        self.assertEqual(mapping[urls[0]], mapping[urls[1]])
        self.assertNotEqual(mapping[urls[0]], mapping[urls[2]])


if __name__ == "__main__":
    unittest.main()
