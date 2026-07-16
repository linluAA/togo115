from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import app.services.subscription.runtime as runtime
from app.services.adapters.telegram.rate_limit import TelegramRequestGate
from app.services.search_metrics import clear_metrics, metrics_snapshot, record_telegram_search, record_115_validation
from app.services.subscription.search import all as search_all_module


class SearchOptimizationTest(unittest.IsolatedAsyncioTestCase):
    def test_subscription_concurrency_is_three(self) -> None:
        self.assertEqual(runtime.SUBSCRIPTION_SEARCH_CONCURRENCY, 3)

    def test_floodwait_gate_increases_interval(self) -> None:
        gate = TelegramRequestGate(0.05)
        class Flood(Exception):
            seconds = 10
        gate.note_error(Flood("FloodWaitError"))
        self.assertGreaterEqual(gate.interval, 0.2)
        self.assertGreaterEqual(gate.flood_events, 1)

    def test_metrics_snapshot_aggregates(self) -> None:
        clear_metrics()
        record_telegram_search({"title": "a", "resolve_ms": 10, "search_ms": 20, "extract_ms": 5, "total_ms": 40, "index_hits": 1})
        record_115_validation({"id": 1, "115_ms": 12, "checked_115": 2, "expired_115": 1, "recheck_115": 0})
        snap = metrics_snapshot()
        self.assertEqual(snap["telegram"]["searches"], 1)
        self.assertEqual(snap["share_115"]["checks"], 2)
        self.assertEqual(snap["concurrency"], 3)
        clear_metrics()

    async def test_search_all_starts_without_waiting_emby(self) -> None:
        started = []

        async def slow_emby(subs, snapshot):
            started.append("emby")
            await asyncio.sleep(0.2)
            started.append("emby_done")

        async def fast_search(sub, snapshot):
            started.append("search")
            return (1, 0, 0)

        with patch.object(search_all_module, "active_subscriptions", return_value=[{"id": 1, "title": "x", "status": "active"}]), \
             patch.object(search_all_module, "library_snapshot_or_none", AsyncMock(return_value={"ok": True})), \
             patch.object(search_all_module, "sync_subscriptions_with_emby_snapshot", side_effect=slow_emby), \
             patch.object(search_all_module, "_search_one", side_effect=fast_search):
            result = await search_all_module.search_all_active_subscriptions()
        self.assertTrue(result["ok"])
        self.assertIn("search", started)
        # Search should have started before emby finished.
        self.assertLess(started.index("search"), started.index("emby_done"))




class IndexAnd115CacheOptimizationTest(unittest.TestCase):
    def test_index_prefilter_terms_drop_years_and_keep_alias(self) -> None:
        from app.services.adapters.telegram.scan.message_index import _index_prefilter_terms

        terms = _index_prefilter_terms(["新攻壳机动队 2026", "攻壳机动队"])
        self.assertTrue(any("攻壳" in term or "机动" in term for term in terms))
        self.assertFalse(any(term.isdigit() for term in terms))

    def test_index_negative_cache_short_circuits_empty_queries(self) -> None:
        from app.services.adapters.telegram.scan import message_index as index_mod

        index_mod._NEGATIVE_INDEX_CACHE.clear()
        sources = ["-100999"]
        queries = ["肯定不存在的剧名XYZABC"]
        first = index_mod.search_telegram_message_index(sources, queries, 5)
        self.assertEqual(first, [])
        # Second call should hit negative cache without needing DB content.
        key = index_mod._negative_cache_key(sources, queries)
        self.assertIn(key, index_mod._NEGATIVE_INDEX_CACHE)
        second = index_mod.search_telegram_message_index(sources, queries, 5)
        self.assertEqual(second, [])

    def test_candidate_rows_use_like_prefilter_when_terms_present(self) -> None:
        import sqlite3
        from app.services.adapters.telegram.scan.message_index import _candidate_rows, _search_blob_for

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE telegram_message_index (
                source TEXT, message_id INTEGER, text TEXT, context TEXT, search_blob TEXT,
                has_115 INTEGER, has_link_hint INTEGER, message_date TEXT, indexed_at TEXT,
                PRIMARY KEY(source, message_id)
            )
            """
        )
        rows_data = [
            ("-1", 1, "其他剧 https://115.com/s/a", "其他剧", 1, 1, None, "t"),
            ("-1", 2, "攻殻機動隊 https://115.com/s/b", "剧集：攻殻機動隊(2026)", 1, 1, None, "t"),
            ("-1", 3, "野狗骨头 https://115.com/s/c", "野狗骨头", 1, 1, None, "t"),
        ]
        for source, mid, text, context, has115, hint, date, idx in rows_data:
            conn.execute(
                "INSERT INTO telegram_message_index VALUES (?,?,?,?,?,?,?,?,?)",
                (source, mid, text, context, _search_blob_for(text, context), has115, hint, date, idx),
            )
        rows = _candidate_rows(conn, ["-1"], ["攻壳机动队"])
        texts = [row["context"] + row["text"] for row in rows]
        self.assertTrue(any("攻殻" in text or "攻壳" in text for text in texts))
        self.assertGreaterEqual(len(rows), 1)
        # Should not need full fallback noise if blob matched.
        self.assertTrue(all("野狗" not in text for text in texts) or len(rows) == 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
