from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.db import close_connection_pool, init_db
from app.services.adapters.telegram.scan import message_index_query as index_query
from app.services.resource_queries import list_recent_resources, invalidate_recent_resources_cache, merge_resource_rows
from app.services.subscription.search.all import _prefer_incremental_telegram


class PerfNextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-perf-next.sqlite3"
        init_db()
        invalidate_recent_resources_cache()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        close_connection_pool()
        self.temp_dir.cleanup()

    def test_prefilter_terms_prefer_longer_stems(self) -> None:
        terms = index_query.index_prefilter_terms(["Hello World 1080p"])
        self.assertTrue(terms)
        self.assertGreaterEqual(len(terms[0]), 2)

    def test_fts_match_query_quotes_tokens(self) -> None:
        match = index_query._fts_match_query(["hello", "nan"])
        self.assertIn("hello", match)
        self.assertIn(" OR ", match)

    def test_prefer_incremental_only_when_no_resource_search_needed(self) -> None:
        self.assertFalse(_prefer_incremental_telegram({"media_type": "movie", "in_library": False}))
        self.assertTrue(_prefer_incremental_telegram({"media_type": "movie", "in_library": True}))
        self.assertFalse(
            _prefer_incremental_telegram(
                {
                    "media_type": "tv",
                    "last_checked_at": "2026-01-01",
                    "tmdb_total_count": 8,
                    "emby_episode_keys": ["1x1"],
                }
            )
        )
        self.assertFalse(_prefer_incremental_telegram({"media_type": "tv", "last_checked_at": ""}))

    def test_recent_resources_cache_hits(self) -> None:
        calls = {"n": 0}

        class FakeConn:
            def execute(self, *args, **kwargs):
                calls["n"] += 1
                class Cur:
                    def fetchall(self_inner):
                        return []
                return Cur()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("app.services.resource_queries.db", return_value=FakeConn()):
            a = list_recent_resources(10, 0)
            b = list_recent_resources(10, 0)
        self.assertEqual(a, [])
        self.assertEqual(b, [])
        self.assertEqual(calls["n"], 1)

    def test_resource_episode_parse_cache_reuses_row_parse(self) -> None:
        calls = {"n": 0}

        def fake_parse(subscription, text):
            calls["n"] += 1
            return {(1, 1)}

        row = {
            "id": 1,
            "subscription_id": 10,
            "subscription_title": "剧集",
            "title": "剧集 S01E01",
            "url": "https://115.com/s/a",
            "message_id": "m1",
            "status": "delivered",
        }
        with patch("app.services.resource_queries.episode_keys_from_text_for_subscription", side_effect=fake_parse):
            merged = merge_resource_rows([dict(row), dict(row)])

        self.assertEqual(len(merged), 1)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
