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




class IndexEarlyReturnHarness(TelegramHistorySearchMixin):
    def __init__(self) -> None:
        self.remote_calls = 0
        self.indexed = [
            SearchResult(
                title="索引命中",
                url="https://115.com/s/index?password=1111",
                source="TelegramIndex",
                message_id="99",
            )
        ]

    def _dedupe_results(self, results):
        return results

    async def _authorized_client_for_search(self):
        return object()

    def _config(self):
        return {"sources": ["-1001"]}

    def _configured_sources(self, config):
        return ["-1001"]

    async def _resolve_dialogs(self, client, sources):
        return [{"entity": "e", "source": sources[0], "canonical": sources[0]}]

    def _history_options(self, config):
        return TelegramHistoryOptions(20, 20, 5, 10, 2, 2)

    def _search_indexed_telegram_messages(self, dialogs, queries):
        return list(self.indexed)

    async def _search_dialogs_concurrently(self, *args, **kwargs):
        self.remote_calls += 1
        return [SearchResult(title="远端", url="https://115.com/s/remote?password=1111", source="tg")]


class SharedStateHarness(TelegramHistorySearchMixin):
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.dialog_history_calls = 0

    async def _authorized_client_for_search(self):
        return object()

    def _config(self):
        return {"sources": ["-1001"]}

    def _configured_sources(self, config):
        return ["-1001"]

    async def _resolve_dialogs(self, client, sources):
        self.resolve_calls += 1
        return [{"entity": "e", "source": sources[0], "canonical": sources[0]}]

    def _history_options(self, config):
        return TelegramHistoryOptions(20, 20, 5, 10, 2, 2)

    def _search_indexed_telegram_messages(self, dialogs, queries):
        return []

    async def _search_dialog_history(self, client, dialog, queries, options, budget, *, incremental=False, shared_state=None):
        self.dialog_history_calls += 1
        return [SearchResult(title="远端", url="https://115.com/s/shared?password=1111", source=str(dialog["canonical"]), message_id="12")]

    def _dedupe_results(self, results):
        return results


class TelegramSearchP1Test(unittest.IsolatedAsyncioTestCase):
    async def test_full_search_returns_index_hits_without_remote(self) -> None:
        harness = IndexEarlyReturnHarness()
        with patch("app.services.adapters.telegram.history.search._expanded_search_queries", return_value=["将夜"]):
            results = await harness.search_history("将夜", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "TelegramIndex")
        self.assertEqual(harness.remote_calls, 0)

    async def test_full_search_force_remote_skips_index(self) -> None:
        from app.services.adapters.telegram.models import TelegramSearchSharedState

        harness = IndexEarlyReturnHarness()
        state = TelegramSearchSharedState(force_remote=True)
        with patch("app.services.adapters.telegram.history.search._expanded_search_queries", return_value=["将夜"]):
            results = await harness.search_history("将夜", [], shared_state=state)
        self.assertEqual(harness.remote_calls, 1)
        self.assertEqual(results[0].url, "https://115.com/s/remote?password=1111")

    async def test_shared_state_reuses_dialogs_between_stages(self) -> None:
        from app.services.adapters.telegram.models import TelegramSearchSharedState

        harness = SharedStateHarness()
        state = TelegramSearchSharedState()
        with patch("app.services.adapters.telegram.history.search._expanded_search_queries", return_value=["将夜"]):
            first = await harness.search_history("将夜", [], shared_state=state)
            second = await harness.search_history("将夜", [], shared_state=state)
        self.assertEqual(harness.resolve_calls, 1)
        self.assertEqual(len(first), 1)
        # second stage should filter the same URL already remembered
        self.assertEqual(second, [])
        self.assertEqual(harness.dialog_history_calls, 2)


if __name__ == "__main__":
    unittest.main()
