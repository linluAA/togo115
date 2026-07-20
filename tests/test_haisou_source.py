from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.db import init_db
from app.services.sources.haisou.client import HaisouApiError, HaisouClient
from app.services.sources.haisou.config import haisou_enabled, haisou_settings, haisou_source_entry
from app.services.sources.haisou.mapper import build_haisou_share_url, map_haisou_items
from app.services.sources.haisou.search import search_haisou
from app.services.sources.rss_torznab import RssTorznabAdapter
from app.services.settings_store import save_setting


class HaisouSourceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-haisou-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def test_mapper_keeps_only_115_and_appends_password(self) -> None:
        items = [
            {
                "hsid": "a",
                "platform": "115",
                "title": "Demo S01E01 1080p",
                "shareUrl": "https://115.com/s/abcDEF",
                "sharePwd": "xy",
            },
            {
                "hsid": "b",
                "platform": "quark",
                "title": "Quark only",
                "shareUrl": "https://pan.quark.cn/s/zzz",
            },
        ]
        mapped = map_haisou_items(items)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].url, "https://115.com/s/abcDEF?password=xy")
        self.assertIn("Demo", mapped[0].title)

    def test_build_url_from_share_code(self) -> None:
        url = build_haisou_share_url({"platform": "115", "shareCode": "code123", "sharePwd": "ab"})
        self.assertEqual(url, "https://115.com/s/code123?password=ab")

    def test_settings_disabled_without_key(self) -> None:
        self.assertFalse(haisou_enabled())
        self.assertIsNone(haisou_source_entry())

    def test_settings_enabled_injects_source(self) -> None:
        save_setting("haisou", {"api_key": "test-key", "enabled": True, "page_size": 10, "platforms": ["115"]})
        cfg = haisou_settings()
        self.assertTrue(haisou_enabled(cfg))
        entry = haisou_source_entry(cfg)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["plugin"], "haisou")
        self.assertEqual(entry["priority"], 10)

        sources = RssTorznabAdapter()._sources()
        self.assertTrue(any(item.get("plugin") == "haisou" for item in sources))

    async def test_search_maps_api_payload(self) -> None:
        save_setting("haisou", {"api_key": "test-key", "enabled": True})
        payload = {
            "items": [
                {
                    "hsid": "hs1",
                    "platform": "115",
                    "title": "Example Show 2024",
                    "shareUrl": "https://115cdn.com/s/share1",
                    "sharePwd": "12",
                }
            ]
        }
        with patch.object(HaisouClient, "search", new=AsyncMock(return_value=payload)):
            results = await search_haisou("Example Show")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].url.startswith("https://115cdn.com/s/share1"))
        self.assertIn("password=12", results[0].url)

    async def test_client_raises_on_nonzero_code_without_retry_when_credits(self) -> None:
        client = HaisouClient(api_key="k")

        class FakeResp:
            status_code = 200

            def json(self):
                return {"code": 1000, "credits": 1, "msg": "busy"}

        class FakeHttp:
            async def post(self, *args, **kwargs):
                return FakeResp()

        with patch("app.services.sources.haisou.client.shared_async_client", return_value=FakeHttp()):
            with self.assertRaises(HaisouApiError) as ctx:
                await client.search("q")
        self.assertEqual(ctx.exception.code, 1000)
        self.assertFalse(ctx.exception.retryable)

    def test_settings_from_builtin_override(self) -> None:
        save_setting(
            "rss_sources",
            {
                "sources": [],
                "builtin_sources": {
                    "builtin_haisou": {
                        "api_key": "override-key",
                        "enabled": True,
                        "page_size": 15,
                        "search_in": "files",
                    }
                },
            },
        )
        cfg = haisou_settings()
        self.assertEqual(cfg["api_key"], "override-key")
        self.assertEqual(cfg["page_size"], 15)
        self.assertEqual(cfg["search_in"], "files")
        sources = RssTorznabAdapter()._sources()
        self.assertTrue(
            any(item.get("plugin") == "haisou" and item.get("api_key") == "override-key" for item in sources)
        )




if __name__ == "__main__":
    unittest.main()
