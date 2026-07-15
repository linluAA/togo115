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


if __name__ == "__main__":
    unittest.main()
