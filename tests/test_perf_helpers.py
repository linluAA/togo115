from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.subscription.search.recent_cache import (
    clear_recent_search_results,
    get_recent_search_results,
    store_recent_search_results,
)
from app.services.subscription.search.share115_cache import Shared115ValidationCache, reset_process_115_cache
from app.services.adapters.pan115 import SHARE_AVAILABLE, SHARE_UNAVAILABLE
from app.services.concurrency import desired_telegram_dialog_concurrency, search_all_wave_size, SUBSCRIPTION_SEARCH_CONCURRENCY


class PerfHelpersTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_recent_search_results()
        reset_process_115_cache()

    def test_recent_search_cache_roundtrip(self) -> None:
        store_recent_search_results(9, [{"id": 1}], incremental_telegram=False)
        hit = get_recent_search_results(9, incremental_telegram=False)
        self.assertEqual(hit, [{"id": 1}])
        self.assertIsNone(get_recent_search_results(9, incremental_telegram=True))

    async def test_availability_many_uses_bounded_probes(self) -> None:
        cache = Shared115ValidationCache(probe_concurrency=2)
        adapter = AsyncMock()
        async def probe(url: str) -> str:
            return SHARE_UNAVAILABLE if "bbb" in url else SHARE_AVAILABLE
        adapter.share_availability = AsyncMock(side_effect=probe)
        cache._adapter = adapter
        urls = [
            "https://115.com/s/aaa?password=1111",
            "https://115.com/s/bbb?password=2222",
            "https://115.com/s/ccc?password=3333",
        ]
        states = await cache.availability_many(urls)
        self.assertEqual(len(states), 3)
        self.assertEqual(states[urls[1]], SHARE_UNAVAILABLE)
        self.assertEqual(adapter.share_availability.await_count, 3)
        # second probe of same url hits adapter again only if not cached at adapter layer;
        # this process cache only coalesces in-flight futures, not completed ones.
        await cache.availability(urls[0])
        self.assertEqual(adapter.share_availability.await_count, 4)

    def test_wave_size_can_exceed_base_when_idle(self) -> None:
        self.assertGreaterEqual(search_all_wave_size(), SUBSCRIPTION_SEARCH_CONCURRENCY)
        self.assertGreaterEqual(desired_telegram_dialog_concurrency(), 1)


if __name__ == "__main__":
    unittest.main()
