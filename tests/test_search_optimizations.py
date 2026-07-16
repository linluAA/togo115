from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import app.services.subscription.runtime as runtime
from app.services.adapters.telegram.rate_limit import TelegramRequestGate
from app.services.search_metrics import clear_metrics, metrics_snapshot, record_telegram_search, record_115_validation, record_attach_outcome
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




    def test_metrics_p95_and_attach_outcomes(self) -> None:
        clear_metrics()
        for total in (10, 20, 30, 40, 100):
            record_telegram_search({
                "title": "x",
                "resolve_ms": total // 4,
                "search_ms": total // 2,
                "extract_ms": total // 5,
                "total_ms": total,
                "index_hits": 1,
            })
        record_115_validation({"id": 1, "115_ms": 12, "checked_115": 2, "expired_115": 1, "recheck_115": 0})
        record_115_validation({"id": 2, "115_ms": 80, "checked_115": 1, "expired_115": 0, "recheck_115": 1})
        record_attach_outcome({"id": 1, "created": 1, "duplicates": 0, "expired_115": 0, "save_failed": 0, "raw_matched": 1, "candidates": 2})
        record_attach_outcome({"id": 2, "created": 0, "duplicates": 2, "expired_115": 1, "save_failed": 0, "raw_matched": 2, "candidates": 3})
        record_attach_outcome({"id": 3, "created": 0, "duplicates": 0, "expired_115": 0, "save_failed": 0, "raw_matched": 0, "candidates": 4})
        snap = metrics_snapshot()
        self.assertEqual(snap["telegram"]["searches"], 5)
        self.assertGreaterEqual(snap["telegram"]["p95_total_ms"], snap["telegram"]["p50_total_ms"])
        self.assertEqual(snap["telegram"]["p95_total_ms"], 100.0)
        self.assertEqual(snap["share_115"]["checks"], 3)
        self.assertGreaterEqual(snap["share_115"]["p95_ms"], snap["share_115"]["p50_ms"])
        self.assertEqual(snap["attach"]["created"], 1)
        self.assertEqual(snap["attach"]["duplicates"], 2)
        self.assertEqual(snap["attach"]["expired"], 1)
        self.assertEqual(snap["attach"]["mismatch"], 1)
        clear_metrics()

    async def test_telegram_source_lock_is_stable_per_source(self) -> None:
        a1 = runtime.telegram_source_lock("channel-a")
        a2 = runtime.telegram_source_lock("channel-a")
        b1 = runtime.telegram_source_lock("channel-b")
        self.assertIs(a1, a2)
        self.assertIsNot(a1, b1)

    async def test_search_semaphore_adapts_to_floodwait_pressure(self) -> None:
        runtime.subscription_search_semaphore = None
        runtime.subscription_search_semaphore_loop = None
        runtime.subscription_search_semaphore_limit = 0
        from app.services.adapters.telegram.rate_limit import telegram_request_gate

        original = float(telegram_request_gate._current_interval)
        try:
            telegram_request_gate._current_interval = 1.0
            sem = runtime.search_semaphore()
            self.assertEqual(sem._value, 1)
            runtime.subscription_search_semaphore = None
            runtime.subscription_search_semaphore_loop = None
            runtime.subscription_search_semaphore_limit = 0
            telegram_request_gate._current_interval = 0.3
            sem2 = runtime.search_semaphore()
            self.assertEqual(sem2._value, 2)
            runtime.subscription_search_semaphore = None
            runtime.subscription_search_semaphore_loop = None
            runtime.subscription_search_semaphore_limit = 0
            telegram_request_gate._current_interval = 0.05
            sem3 = runtime.search_semaphore()
            self.assertEqual(sem3._value, runtime.SUBSCRIPTION_SEARCH_CONCURRENCY)
        finally:
            telegram_request_gate._current_interval = original
            runtime.subscription_search_semaphore = None
            runtime.subscription_search_semaphore_loop = None
            runtime.subscription_search_semaphore_limit = 0



    async def test_search_all_runs_in_waves(self) -> None:
        started: list[int] = []
        max_inflight = {"value": 0}
        inflight = {"value": 0}

        async def slow_search(sub, snapshot):
            sid = int(sub["id"])
            started.append(sid)
            inflight["value"] += 1
            max_inflight["value"] = max(max_inflight["value"], inflight["value"])
            await asyncio.sleep(0.05)
            inflight["value"] -= 1
            return (1, 0, 0)

        subs = [{"id": i, "title": f"t{i}", "status": "active"} for i in range(1, 7)]
        with patch.object(search_all_module, "active_subscriptions", return_value=subs), \
             patch.object(search_all_module, "library_snapshot_or_none", AsyncMock(return_value={"ok": True})), \
             patch.object(search_all_module, "sync_subscriptions_with_emby_snapshot", AsyncMock(return_value=None)), \
             patch.object(search_all_module, "_search_one", side_effect=slow_search), \
             patch.object(runtime, "search_all_wave_size", return_value=2), \
             patch.object(runtime, "SEARCH_ALL_WAVE_STAGGER_SECONDS", 0.0):
            result = await search_all_module.search_all_active_subscriptions()
        self.assertTrue(result["ok"])
        self.assertEqual(result["searched"], 6)
        self.assertEqual(started, [1, 2, 3, 4, 5, 6])
        self.assertLessEqual(max_inflight["value"], 2)

    async def test_search_semaphore_refreshes_when_idle(self) -> None:
        runtime.subscription_search_semaphore = None
        runtime.subscription_search_semaphore_loop = None
        runtime.subscription_search_semaphore_limit = 0
        from app.services.adapters.telegram.rate_limit import telegram_request_gate

        original = float(telegram_request_gate._current_interval)
        try:
            telegram_request_gate._current_interval = 0.05
            first = runtime.search_semaphore()
            self.assertEqual(runtime.subscription_search_semaphore_limit, runtime.SUBSCRIPTION_SEARCH_CONCURRENCY)
            telegram_request_gate._current_interval = 1.0
            # Idle semaphore (full permits) can rebuild to a tighter limit.
            second = runtime.search_semaphore()
            self.assertEqual(runtime.subscription_search_semaphore_limit, 1)
            self.assertIsNot(first, second)
            self.assertEqual(second._value, 1)
        finally:
            telegram_request_gate._current_interval = original
            runtime.subscription_search_semaphore = None
            runtime.subscription_search_semaphore_loop = None
            runtime.subscription_search_semaphore_limit = 0



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
