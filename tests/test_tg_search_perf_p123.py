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
from app.services.adapters.telegram.history.fast import TelegramFastSearchMixin
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


class FastMultiQueryFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_fast_search_tries_second_query_when_first_is_empty(self) -> None:
        class Harness(TelegramFastSearchMixin):
            def __init__(self) -> None:
                self.queries: list[str] = []

            async def _authorized_client_for_search(self):
                return object()

            def _config(self):
                return {"sources": ["-1001"]}

            def _configured_sources(self, config):
                return ["-1001"]

            async def _resolve_dialogs_for_fast_search(self, client, source_values):
                return [{"entity": "e", "source": "-1001", "canonical": "-1001"}]

            def _server_search_queries(self, queries):
                return ["primary", "alias"]

            async def _search_dialogs_fast(self, client, dialogs, query, budget, *, shared_state=None):
                self.queries.append(query)
                if query == "alias":
                    return [SearchResult(title="hit", url="https://115.com/s/alias?password=1111", source="tg")]
                return []

            def _dedupe_results(self, results):
                return results

        harness = Harness()
        with patch("app.services.adapters.telegram.history.fast.search_telegram_message_index", return_value=[]):
            results = await harness.search_history_fast("金特务", [])

        self.assertEqual(harness.queries, ["primary", "alias"])
        self.assertEqual(results[0].url, "https://115.com/s/alias?password=1111")


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
        self.assertEqual(TELEGRAM_INDEX_PREWARM_LIMIT, 80)
        self.assertEqual(TELEGRAM_INDEX_PREWARM_DELTA_LIMIT, 40)

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
    async def test_empty_streak_no_longer_cancels_remaining(self) -> None:
        class Harness(TelegramDialogSearchMixin):
            def __init__(self) -> None:
                self.calls = 0

            async def _search_dialog_history(self, *args, **kwargs):
                self.calls += 1
                await asyncio.sleep(0.01)
                if self.calls == 8:
                    return [SearchResult(title="late", url="https://115.com/s/late", source="d8")], 1
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
        self.assertEqual([result.url for result in results], ["https://115.com/s/late"])
        self.assertEqual(int(metrics.get("empty_early_stop") or 0), 0)
        self.assertEqual(metrics.get("searched_dialogs"), 8)
        self.assertEqual(harness.calls, 8)


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

        self.assertEqual(TELEGRAM_INDEX_MAX_AGE_DAYS, 28)
        # No table / empty DB should not raise.
        deleted = prune_old_index_rows(max_age_days=21)
        self.assertIsInstance(deleted, int)



class ProcessQueryCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.services.adapters.telegram.history.query_result_cache import clear_query_result_cache
        clear_query_result_cache()

    def tearDown(self) -> None:
        from app.services.adapters.telegram.history.query_result_cache import clear_query_result_cache
        clear_query_result_cache()

    def test_positive_and_negative_cache(self) -> None:
        from app.services.adapters.telegram.history.query_result_cache import (
            get_cached_query_results,
            set_cached_query_results,
        )
        hits = [SearchResult(title="t", url="https://115.com/s/x", source="src")]
        set_cached_query_results("src", "q", hits)
        cached = get_cached_query_results("src", "q")
        self.assertEqual(len(cached or []), 1)
        set_cached_query_results("src", "empty", [])
        empty = get_cached_query_results("src", "empty")
        self.assertIsNotNone(empty)
        self.assertEqual(empty, [])


class DialogCooldownRankTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_process_dialog_hit_scores()

    def tearDown(self) -> None:
        clear_process_dialog_hit_scores()

    def test_slow_dialog_demoted(self) -> None:
        from app.services.adapters.telegram.history.dialog_rank import note_dialog_latency, rank_dialogs
        note_dialog_hit("fast", 1)
        note_dialog_latency("slow", 4000, had_hits=False)
        ranked = rank_dialogs([{"canonical": "slow"}, {"canonical": "fast"}])
        self.assertEqual([d["canonical"] for d in ranked], ["fast", "slow"])


class FirstQueryEarlyStopTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_second_query_when_first_hits(self) -> None:
        class Harness(TelegramDialogSearchQueryMixin):
            def __init__(self) -> None:
                self.queries: list[str] = []

            def _server_search_queries(self, queries):
                return ["q1", "q2"]

            async def _search_dialog_query(self, client, entity, source, query, options, budget, seen_messages, stats, *, shared_state=None):
                self.queries.append(query)
                if query == "q1":
                    return [SearchResult(title="t", url="https://115.com/s/a", source=source)]
                return []

            async def _scan_recent_messages(self, *args, **kwargs):
                raise AssertionError("recent should not run when server hits")

        harness = Harness()
        options = TelegramHistoryOptions(20, 20, 4, 3.0, 1.0, 1.0)
        budget = TelegramSearchBudget(3.0)
        hits, _ = await harness._search_dialog_history(
            object(),
            {"entity": object(), "canonical": "src"},
            ["q1", "q2"],
            options,
            budget,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(harness.queries, ["q1"])


class TargetEarlyStopTest(unittest.IsolatedAsyncioTestCase):
    async def test_target_met_no_longer_cancels_pending(self) -> None:
        class Harness(TelegramDialogSearchMixin):
            def __init__(self) -> None:
                self.calls = 0

            async def _search_dialog_history(self, *args, **kwargs):
                self.calls += 1
                await asyncio.sleep(0.02)
                return [SearchResult(title="t", url=f"https://115.com/s/{self.calls}", source="d")], 5

        harness = Harness()
        dialogs = [{"canonical": f"d{i}", "entity": object(), "source": f"d{i}"} for i in range(6)]
        options = TelegramHistoryOptions(20, 20, 4, 5.0, 1.0, 1.0)
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
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(harness.calls, 6)
        self.assertEqual(metrics.get("searched_dialogs"), 6)
        self.assertEqual(int(metrics.get("target_early_stop") or 0), 0)


if __name__ == "__main__":
    unittest.main()
