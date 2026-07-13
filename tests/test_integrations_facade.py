from __future__ import annotations

import unittest

from app.services import integrations
from app.services.adapters.media import TmdbAdapter
from app.services.adapters.pan115 import Pan115Adapter
from app.services.adapters.telegram import TelegramClientAdapter
from app.services.sources.rss_torznab import RssTorznabAdapter
from app.services.types import SearchResult


class IntegrationsFacadeTest(unittest.TestCase):
    def test_facade_exports_compatibility_symbols(self) -> None:
        expected = {
            "Pan115Adapter",
            "RssTorznabAdapter",
            "SearchResult",
            "TelegramClientAdapter",
            "TmdbAdapter",
            "add_log",
            "context_for_115_link",
            "extract_download_links",
            "get_flow",
            "get_setting",
            "httpx",
            "module_proxy",
            "save_flow",
            "save_setting",
            "telegram_message_text",
        }

        self.assertEqual(set(integrations.__all__), expected)

    def test_facade_points_to_real_implementations(self) -> None:
        self.assertIs(integrations.Pan115Adapter, Pan115Adapter)
        self.assertIs(integrations.RssTorznabAdapter, RssTorznabAdapter)
        self.assertIs(integrations.SearchResult, SearchResult)
        self.assertIs(integrations.TelegramClientAdapter, TelegramClientAdapter)
        self.assertIs(integrations.TmdbAdapter, TmdbAdapter)

    def test_facade_keeps_patch_targets_available(self) -> None:
        self.assertTrue(callable(integrations.add_log))
        self.assertTrue(callable(integrations.get_setting))
        self.assertTrue(callable(integrations.save_setting))
        self.assertTrue(callable(integrations.get_flow))
        self.assertTrue(callable(integrations.save_flow))
        self.assertTrue(callable(integrations.module_proxy))
        self.assertTrue(hasattr(integrations.httpx, "AsyncClient"))
