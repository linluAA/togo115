from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.adapters.telegram.history.search import TelegramHistorySearchMixin
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget
from app.services.subscription.delivery.link_validation import pick_first_available_115_result
from app.services.types import SearchResult


class HistoryHarness(TelegramHistorySearchMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _search_dialog_query(self, *args, **kwargs):
        self.calls.append("server")
        return [SearchResult(title="命中", url="https://115.com/s/ok?password=1111", source="tg")]

    async def _scan_recent_messages(self, *args, **kwargs):
        self.calls.append("recent")
        return [SearchResult(title="最近", url="https://115.com/s/recent?password=1111", source="tg")]


class TelegramSearchPerfTest(unittest.IsolatedAsyncioTestCase):
    async def test_non_incremental_prefers_server_search_before_recent(self) -> None:
        harness = HistoryHarness()
        options = TelegramHistoryOptions(
            history_limit=20,
            fallback_scan_limit=20,
            messages_per_query=5,
            total_budget=10,
            query_budget=2,
            recent_budget=2,
        )
        budget = TelegramSearchBudget(10)
        results = await harness._search_dialog_history(
            client=None,
            dialog={"entity": "e", "canonical": "source"},
            queries=["将夜"],
            options=options,
            budget=budget,
            incremental=False,
        )
        self.assertEqual(harness.calls[0], "server")
        self.assertNotIn("recent", harness.calls)
        self.assertEqual(results[0].url, "https://115.com/s/ok?password=1111")

    async def test_non_incremental_falls_back_to_recent_when_server_empty(self) -> None:
        harness = HistoryHarness()

        async def empty_server(*args, **kwargs):
            harness.calls.append("server")
            return []

        harness._search_dialog_query = empty_server  # type: ignore[method-assign]
        options = TelegramHistoryOptions(
            history_limit=20,
            fallback_scan_limit=20,
            messages_per_query=5,
            total_budget=10,
            query_budget=2,
            recent_budget=2,
        )
        results = await harness._search_dialog_history(
            client=None,
            dialog={"entity": "e", "canonical": "source"},
            queries=["将夜"],
            options=options,
            budget=TelegramSearchBudget(10),
            incremental=False,
        )
        self.assertEqual(harness.calls, ["server", "recent"])
        self.assertEqual(results[0].url, "https://115.com/s/recent?password=1111")

    async def test_pick_first_available_stops_after_first_ok(self) -> None:
        calls: list[str] = []

        class FakePan:
            async def share_availability(self, url: str) -> str:
                calls.append(url)
                if "bad" in url:
                    return "unavailable"
                return "available"

        results = [
            SearchResult(title="bad", url="https://115.com/s/bad?password=1", source="tg"),
            SearchResult(title="ok", url="https://115.com/s/ok?password=1", source="tg"),
            SearchResult(title="later", url="https://115.com/s/later?password=1", source="tg"),
        ]
        import app.services.subscription.delivery.link_validation as module

        old = module.Pan115Adapter
        module.Pan115Adapter = FakePan
        try:
            first, recheck, report, first_is_recheck = await pick_first_available_115_result(results)
        finally:
            module.Pan115Adapter = old

        self.assertIsNotNone(first)
        self.assertEqual(first.url, "https://115.com/s/ok?password=1")
        self.assertEqual(calls, [
            "https://115.com/s/bad?password=1",
            "https://115.com/s/ok?password=1",
        ])
        self.assertEqual(report["checked_115"], 2)
        self.assertEqual(report["expired_115"], 1)
        self.assertEqual(recheck, [])


if __name__ == "__main__":
    unittest.main()
