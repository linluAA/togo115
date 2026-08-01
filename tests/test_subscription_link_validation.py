from __future__ import annotations

import asyncio
import time
import unittest

from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.delivery.link_validation import classify_115_results


class LinkValidationConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_115_links_are_checked_concurrently_and_deduped(self) -> None:
        calls: list[str] = []

        class FakePan115:
            async def share_availability(self, url: str) -> str:
                calls.append(url)
                await asyncio.sleep(0.03)
                return "available"

        results = [
            SearchResult(title="A", url="https://115.com/s/a?password=1111", source="tg"),
            SearchResult(title="A duplicate", url="https://115.com/s/a?password=1111", source="tg"),
            SearchResult(title="B", url="https://115.com/s/b?password=2222", source="tg"),
            SearchResult(title="C", url="https://115.com/s/c?password=3333", source="tg"),
        ]

        import app.services.subscription.search.share115_cache as share_cache_module
        from app.services.subscription.search.share115_cache import reset_process_115_cache

        reset_process_115_cache()
        old_adapter = share_cache_module.Pan115Adapter
        share_cache_module.Pan115Adapter = FakePan115
        try:
            started = time.perf_counter()
            filtered, recheck, report = await classify_115_results(results)
            elapsed = time.perf_counter() - started
        finally:
            share_cache_module.Pan115Adapter = old_adapter
            reset_process_115_cache()

        self.assertEqual(len(filtered), 4)
        self.assertEqual(recheck, [])
        self.assertEqual(report["checked_115"], 3)
        self.assertEqual(sorted(calls), sorted(set(calls)))
        self.assertLess(elapsed, 0.08)

    async def test_unknown_115_links_still_pass_through_for_delivery(self) -> None:
        class FakePan115:
            async def share_availability(self, url: str) -> str:
                return "unknown"

        results = [SearchResult(title="A", url="https://115.com/s/a?password=1111", source="tg")]

        import app.services.subscription.search.share115_cache as share_cache_module
        from app.services.subscription.search.share115_cache import reset_process_115_cache

        reset_process_115_cache()
        old_adapter = share_cache_module.Pan115Adapter
        share_cache_module.Pan115Adapter = FakePan115
        try:
            filtered, recheck, report = await classify_115_results(results)
        finally:
            share_cache_module.Pan115Adapter = old_adapter
            reset_process_115_cache()

        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(recheck), 1)
        self.assertEqual(report["recheck_115"], 1)
