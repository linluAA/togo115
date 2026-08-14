from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.subscription.search.recent_cache import (
    clear_recent_search_results,
    get_recent_search_results,
    store_recent_search_results,
)
from app.services.adapters.pan115 import SHARE_AVAILABLE, SHARE_UNAVAILABLE
from app.services.concurrency import desired_telegram_dialog_concurrency, search_all_wave_size, SUBSCRIPTION_SEARCH_CONCURRENCY


class PerfHelpersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_recent_search_results()

    def test_recent_search_cache_roundtrip(self) -> None:
        store_recent_search_results(9, [{"id": 1}], incremental_telegram=False)
        hit = get_recent_search_results(9, incremental_telegram=False)
        self.assertEqual(hit, [{"id": 1}])
        self.assertIsNone(get_recent_search_results(9, incremental_telegram=True))

    def test_empty_recent_search_result_is_not_cached(self) -> None:
        store_recent_search_results(9, [], incremental_telegram=False)
        self.assertIsNone(get_recent_search_results(9, incremental_telegram=False))

    def test_wave_size_can_exceed_base_when_idle(self) -> None:
        self.assertGreaterEqual(search_all_wave_size(), SUBSCRIPTION_SEARCH_CONCURRENCY)
        self.assertGreaterEqual(desired_telegram_dialog_concurrency(), 1)


if __name__ == "__main__":
    unittest.main()