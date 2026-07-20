from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.adapters.telegram.history.config import adaptive_messages_per_query, server_search_queries
from app.services.adapters.telegram.history.dialog_rank import (
    clear_process_dialog_hit_scores,
    note_dialog_hit,
    rank_dialogs,
)
from app.services.adapters.telegram.history.dialog_search import (
    TELEGRAM_EMPTY_DIALOG_STREAK,
    TelegramDialogSearchMixin,
)
from app.services.adapters.telegram.history.dialog_search_query import TelegramDialogSearchQueryMixin
from app.services.adapters.telegram.history.prewarm import (
    TELEGRAM_INDEX_PREWARM_DELTA_LIMIT,
    TELEGRAM_INDEX_PREWARM_LIMIT,
)
from app.services.adapters.telegram.models import TelegramHistoryOptions, TelegramSearchBudget, TelegramSearchSharedState
from app.services.types import SearchResult


class DialogRankTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_process_dialog_hit_scores()

    def tearDown(self) -> None:
        clear_process_dialog_hit_scores()

    def test_rank_prefers_preferred_then_hit_scores(self) -> None:
        dialogs = [
            {"canonical": "a"},
            {"canonical": "b"},
            {"canonical": "c"},
        ]
        note_dialog_hit("c", 5)
        ranked = rank_dialogs(dialogs, preferred_sources=["b"], hit_scores={"a": 2})
        self.assertEqual([d["canonical"] for d in ranked], ["b", "c", "a"])


class SharedStateCacheTest(unittest.TestCase):
    def test_query_dialog_cache_roundtrip(self) -> None:
        state = TelegramSearchSharedState()
        hits = [SearchResult(title="t", url="https://115.com/s/x", source="src")]
        state.set_cached_query_dialog_results("src", "q", hits)
        cached = state.get_cached_query_dialog_results("src", "q")
        self.assertEqual(len(cached or []), 1)
        self.assertEqual(cached[0].url, hits[0].url)

    def test_note_dialog_hits(self) -> None:
        state = TelegramSearchSharedState()
        state.note_dialog_hits("ch1", 2)
        state.note_dialog_hits("ch1", 1)
        self.assertEqual(state.dialog_hit_scores["ch1"], 3)


class AdaptiveMessagesTest(unittest.TestCase):
    def test_adaptive_messages_shrinks_when_p95_high(self) -> None:
        with patch(
            "app.services.metrics.snapshot.metrics_snapshot",
            return_value={"telegram": {"p95_extract_ms": 1200}},
        ):
            self.assertEqual(adaptive_messages_per_query(12), 5)

    def test_adaptive_messages_keeps_base_when_no_samples(self) -> None:
        with patch(
            "app.services.metrics.snapshot.metrics_snapshot",
            return_value={"telegram": {"p95_extract_ms": 0}},
        ):
            self.assertEqual(adaptive_messages_per_query(12), 12)


class PrewarmFreshnessTest(unittest.TestCase):
    def test_prewarm_limits_raised(self) -> None:
        self.assertEqual(TELEGRAM_INDEX_PREWARM_LIMIT, 60)
        self.assertEqual(TELEGRAM_INDEX_PREWARM_DELTA_LIMIT, 30)

    def test_server_search_query_limit_still_two(self) -> None:
        queries = server_search_queries(["Alpha 2024", "Alpha", "Beta 2024", "Gamma"], limit=2)
        self.assertEqual(len(queries), 2)


class MessageSuggestAndBodyExtractTest(unittest.IsolatedAsyncioTestCase):
    async def test_body_only_extracts_direct_115(self) -> None:
        mixin = TelegramDialogSearchQueryMixin()
        message = SimpleNamespace(id=9, raw_text="将夜 https://115.com/s/abc?password=1", message="将夜 https://115.com/s/abc?password=1", buttons=[])
        # telegram_message_text may use different attrs - patch it
        with patch(
            "app.services.adapters.telegram.history.dialog_search_query.telegram_message_text",
            return_value="将夜 https://115.com/s/abc?password=1",
        ):
            hits = await mixin._body_only_extract_message_links(
                "src",
                message,
                "将夜",
                set(),
                __import__("app.services.adapters.telegram.pipeline", fromlist=["TelegramPipelineStats"]).TelegramPipelineStats(),
            )
        self.assertGreaterEqual(len(hits), 1)
        self.assertTrue(any("115.com/s/abc" in hit.url for hit in hits))

    def test_message_suggests_links(self) -> None:
        mixin = TelegramDialogSearchQueryMixin()
        with patch(
            "app.services.adapters.telegram.history.dialog_search_query.telegram_message_text",
            return_value="plain title only",
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.message_has_link_button_hint",
            return_value=False,
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.text_has_external_resource_page_hint",
            return_value=False,
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.extract_115_links",
            return_value=[],
        ):
            self.assertFalse(mixin._message_suggests_resource_links(SimpleNamespace(id=1)))
        with patch(
            "app.services.adapters.telegram.history.dialog_search_query.telegram_message_text",
            return_value="x magnet:?xt=urn:btih:abcdef",
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.message_has_link_button_hint",
            return_value=False,
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.text_has_external_resource_page_hint",
            return_value=False,
        ), patch(
            "app.services.adapters.telegram.history.dialog_search_query.extract_115_links",
            return_value=[],
        ):
            self.assertTrue(mixin._message_suggests_resource_links(SimpleNamespace(id=2)))


class EmptyEarlyStopTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_streak_cancels_remaining(self) -> None:
        class Harness(TelegramDialogSearchMixin):
            def __init__(self) -> None:
                self.calls = 0

            async def _search_dialog_history(self, *args, **kwargs):
                self.calls += 1
                await asyncio.sleep(0.01)
                return [], 1

        harness = Harness()
        dialogs = [{"canonical": f"d{i}", "entity": object(), "source": f"d{i}"} for i in range(8)]
        options = TelegramHistoryOptions(
            history_limit=20,
            fallback_scan_limit=20,
            messages_per_query=4,
            total_budget=5.0,
            query_budget=1.0,
            recent_budget=1.0,
        )
        budget = TelegramSearchBudget(5.0)
        with patch("app.services.adapters.telegram.history.dialog_search.runtime.telegram_dialog_search_semaphore", return_value=asyncio.Semaphore(2)):
            with patch("app.services.adapters.telegram.history.dialog_search.runtime.telegram_source_lock") as lock:
                class _CM:
                    async def __aenter__(self):
                        return None
                    async def __aexit__(self, *a):
                        return False
                lock.return_value = _CM()
                with patch("app.services.adapters.telegram.history.dialog_search.telegram_request_gate") as gate:
                    gate.wait = AsyncMock()
                    gate.note_error = lambda *a, **k: None
                    results, metrics = await harness._search_dialogs_concurrently(
                        client=object(),
                        dialogs=dialogs,
                        queries=["q"],
                        options=options,
                        budget=budget,
                    )
        self.assertEqual(results, [])
        self.assertGreaterEqual(int(metrics.get("empty_early_stop") or 0), TELEGRAM_EMPTY_DIALOG_STREAK)
        self.assertLess(harness.calls, 8)


class QueryCacheInDialogQueryTest(unittest.IsolatedAsyncioTestCase):
    async def test_cached_query_skips_remote_fetch(self) -> None:
        class Harness(TelegramDialogSearchQueryMixin):
            def __init__(self) -> None:
                self.fetch_calls = 0

            async def _get_search_messages(self, *args, **kwargs):
                self.fetch_calls += 1
                return []

            def _index_telegram_messages(self, *args, **kwargs):
                return None

            def _server_search_queries(self, queries):
                return queries

        state = TelegramSearchSharedState()
        cached = [SearchResult(title="t", url="https://115.com/s/z", source="src")]
        state.set_cached_query_dialog_results("src", "q", cached)
        harness = Harness()
        options = TelegramHistoryOptions(20, 20, 4, 3.0, 1.0, 1.0)
        budget = TelegramSearchBudget(3.0)
        stats: dict = {"searched": 0, "fallback": 0, "links": 0, "timeouts": 0, "skipped_no_link_hint": 0}
        hits = await harness._search_dialog_query(
            object(), object(), "src", "q", options, budget, set(), stats, shared_state=state
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(harness.fetch_calls, 0)
        self.assertEqual(stats.get("cache_hits"), 1)


class IndexAgePruneTest(unittest.TestCase):
    def test_prune_old_index_rows_export(self) -> None:
        from app.services.adapters.telegram.scan.message_index import (
            TELEGRAM_INDEX_MAX_AGE_DAYS,
            prune_old_index_rows,
        )

        self.assertEqual(TELEGRAM_INDEX_MAX_AGE_DAYS, 21)
        # No table / empty DB should not raise.
        deleted = prune_old_index_rows(max_age_days=21)
        self.assertIsInstance(deleted, int)


if __name__ == "__main__":
    unittest.main()
