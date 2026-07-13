import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.db import init_db
from app.services.integrations import RssTorznabAdapter, SearchResult, TelegramClientAdapter, TmdbAdapter, context_for_115_link, extract_download_links, telegram_message_text
from app.services.sources.rss_torznab_hdhive import extract_hdhive_resource_candidates, order_hdhive_candidates
from app.services.subscription_matching import result_matches_subscription


class RssTorznabTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-rss-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    async def test_tmdb_trending_items_fetches_multiple_pages_up_to_limit(self) -> None:
        requested_pages: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", "1"))
            requested_pages.append(page)
            offset = (page - 1) * 20
            items = [{"id": offset + index, "name": f"剧集 {offset + index}"} for index in range(1, 21)]
            if page == 2:
                items[0]["id"] = 1
            return httpx.Response(200, json={"results": items})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            items = await TmdbAdapter()._trending_items(client, "tv", "key", 45)

        self.assertCountEqual(requested_pages, [1, 2, 3])
        self.assertEqual(len(items), 45)
        self.assertEqual(len({item["id"] for item in items}), 45)

    def test_extract_download_links_includes_magnet_and_torrent(self) -> None:
        text = "magnet:?xt=urn:btih:abc123 http://example.com/file.torrent 115cdn.com/s/abc123"
        links = extract_download_links(text)
        self.assertIn("magnet:?xt=urn:btih:abc123", links)
        self.assertIn("http://example.com/file.torrent", links)
        self.assertIn("https://115cdn.com/s/abc123", links)

    def test_extract_download_links_ignores_incomplete_115_share_url(self) -> None:
        links = extract_download_links("占位链接：https://115.com/s/")

        self.assertNotIn("https://115.com/s/", links)
        self.assertEqual(links, [])

    def test_extract_download_links_builds_magnet_from_btih_hash(self) -> None:
        text = "种子哈希：DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9"
        links = extract_download_links(text)

        self.assertIn("magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9", links)

    def test_magnet_web_page_parse_builds_magnet_from_stripped_hash(self) -> None:
        adapter = RssTorznabAdapter()
        html = """
        <html><head><title>宝莱坞机器人之恋 - 磁力链接与种子详情 - BT1207</title></head><body>
          <ul><li>种子哈希：</li><li>DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9</li></ul>
        </body></html>
        """
        source = {"name": "BT1207", "type": "magnet_web", "url": "https://bt1207to.cc/", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://bt1207to.cc/detail/test/hash", html)

        self.assertEqual(results[0].url, "magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9")

    def test_site_plugin_page_parse_ignores_115_and_keeps_magnet(self) -> None:
        adapter = RssTorznabAdapter()
        html = """
        <html><head><title>灿烂的风和海</title></head><body>
          <a href="https://115.com/s/swssxf43nbi?password=8888">115</a>
          <a href="magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9">磁力</a>
        </body></html>
        """
        source = {"name": "BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True}

        results = adapter._parse_magnet_web_page(source, "https://bt1207to.cc/detail/test/hash", html)

        self.assertEqual([item.url for item in results], ["magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9"])

    def test_bt1207_detail_title_ignores_recommendation_noise(self) -> None:
        adapter = RssTorznabAdapter()
        html = """
        <html><head><title>斗罗大陆3D动画 - 磁力链接与种子详情 - BT1207</title></head><body>
          <section><h2>精品推荐</h2><p>磁力链接</p><p>magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9</p></section>
        </body></html>
        """
        source = {"name": "BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://bt1207to.cc/detail/test/hash", html)

        self.assertEqual(results[0].title, "斗罗大陆3D动画")

    def test_bt1207_detail_title_prefers_search_card_context(self) -> None:
        adapter = RssTorznabAdapter()
        html = """
        <html><head><title>这个灵活的年轻女孩被强壮的黑色螺柱主宰 - BT1207</title></head><body>
          <section><h2>精品推荐</h2><p>磁力链接</p><p>magnet:?xt=urn:btih:DB7F7B1C023B944805B2DC2B1854B241DE8BA7C9</p></section>
        </body></html>
        """
        source_context = "【yiyidj.org】大主宰(2023)4KDoVi高码率[杜比音效][更新76集]"
        source = {"name": "BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://bt1207to.cc/detail/test/hash", html, source_context)

        self.assertIn("大主宰", results[0].title)

    def test_search_queries_expand_year_variants(self) -> None:
        adapter = RssTorznabAdapter()
        queries = adapter._search_queries("大主宰 2023", ["1080p"])

        self.assertIn("大主宰", queries)
        self.assertIn("大主宰 (2023)", queries)
        self.assertIn("大主宰（2023）", queries)
        self.assertIn("大主宰 1080p", queries)

    async def test_site_plugin_test_source_returns_diagnostic_for_zero_results(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True}
        request = httpx.Request("GET", "https://bt1207to.cc/search?keyword=test")
        response = httpx.Response(
            200,
            request=request,
            text="<html><head><title>BT1207 搜索结果</title></head><body><p>没有磁力</p></body></html>",
        )

        with patch.object(adapter, "_get_magnet_web_page", new=AsyncMock(return_value=response)):
            result = await adapter.test_source(source, "斗罗大陆")

        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], 0)
        self.assertEqual(result["query"], "斗罗大陆")
        self.assertIn("diagnostic", result)
        self.assertEqual(result["diagnostic"]["detail_candidates"], 0)

    def test_extract_115_links_accepts_wrapped_share_url(self) -> None:
        text = "链接：https://115.com/s\n/swssxf43nbi?password=8888"
        links = extract_download_links(text)

        self.assertIn("https://115.com/s/swssxf43nbi?password=8888", links)

    def test_extract_115_links_accepts_invisible_and_fullwidth_url_chars(self) -> None:
        text = "链接：https：／／115\u200b.com／s／swssxf43nbi？password＝8888"
        links = extract_download_links(text)

        self.assertIn("https://115.com/s/swssxf43nbi?password=8888", links)

    def test_extract_115_links_cuts_trailing_telegram_text_after_password(self) -> None:
        text = "https://115cdn.com/s/swsl8r73n1t?password=j970&\n\n❤❤❤ 人人为我我为人人 欢迎投稿"
        links = extract_download_links(text)

        self.assertEqual(links, ["https://115cdn.com/s/swsl8r73n1t?password=j970"])

    def test_extract_115_links_attaches_nearby_receive_code(self) -> None:
        text = "link: https://115.com/s/swssxf43nbi\ncode: 8888"
        links = extract_download_links(text)

        self.assertIn("https://115.com/s/swssxf43nbi?password=8888", links)
        self.assertNotIn("https://115.com/s/swssxf43nbi8888", links)

    async def test_telegram_links_from_message_uses_message_and_entity_urls(self) -> None:
        class Entity:
            url = "https://115.com/s/entitycode?password=8888"

        class Message:
            id = 7
            raw_text = ""
            message = "电视剧：英雄 (2006) S01E01-E23\n链接：https://115.com/s\n/swslzk73nbi?password=8888"
            entities = [Entity()]
            buttons = None

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(None, Message(), "telegram:test")
        urls = {result.url for result in results}

        self.assertIn("https://115.com/s/swslzk73nbi?password=8888", urls)
        self.assertIn("https://115.com/s/entitycode?password=8888", urls)
        self.assertIn("英雄", telegram_message_text(Message()))

    async def test_telegram_message_text_uses_get_entities_text(self) -> None:
        class UrlEntity:
            url = ""

        class TextUrlEntity:
            url = "https://115.com/s/texturlcode?password=8888"

        class Message:
            raw_text = ""
            message = ""
            entities = []
            buttons = None

            def get_entities_text(self):
                return [(UrlEntity(), "https://115.com/s/entitytext?password=8888"), (TextUrlEntity(), "点我查看")]

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(None, Message(), "telegram:test")
        urls = {result.url for result in results}

        self.assertIn("https://115.com/s/entitytext?password=8888", urls)
        self.assertIn("https://115.com/s/texturlcode?password=8888", urls)

    async def test_telegram_links_from_same_media_group_are_scanned(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = 123456
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = object()

        class Client:
            async def get_messages(self, peer, ids):
                self.peer = peer
                self.ids = ids
                return [
                    Message(9, "封面"),
                    Message(10, "电视剧：大主宰 (2023) S01E01-E80"),
                    Message(11, "链接：https://115.com/s/swslzrw3nbi?password=8888"),
                ]

        adapter = TelegramClientAdapter()
        client = Client()
        results = await adapter._links_from_message(client, Message(10, "电视剧：大主宰 (2023) S01E01-E80"), "telegram:test", "dialog-entity")

        self.assertEqual(results[0].url, "https://115.com/s/swslzrw3nbi?password=8888")
        self.assertIn("大主宰", results[0].context)
        self.assertEqual(client.peer, "dialog-entity")

    async def test_telegram_realtime_link_only_message_uses_nearby_title_context(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def get_messages(self, peer, ids):
                return [
                    Message(40, "Drama (2024) S01E06 1080p"),
                    Message(41, "https://115.com/s/dramacode?password=8888"),
                ]

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(Client(), Message(41, "https://115.com/s/dramacode?password=8888"), "telegram:test", "dialog-entity")
        subscription = {
            "title": "Drama",
            "media_type": "tv",
            "keywords": ["Drama"],
            "release_year": 2024,
            "tmdb_total_count": 10,
            "emby_episode_keys": ["1x1", "1x2", "1x3", "1x4", "1x5"],
        }

        self.assertEqual(results[0].url, "https://115.com/s/dramacode?password=8888")
        self.assertIn("Drama", results[0].context)
        self.assertTrue(result_matches_subscription(subscription, results[0]))

    async def test_telegram_links_from_nearby_link_only_message_are_scanned_for_search_hit(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def get_messages(self, peer, ids):
                return [
                    Message(20, "电视剧：大主宰 (2023) S01E01-E80"),
                    Message(21, "链接：https://115.com/s/swslzrw3nbi?password=8888"),
                ]

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(Client(), Message(20, "电视剧：大主宰 (2023) S01E01-E80"), "telegram:test", "dialog-entity", ["大主宰"])

        self.assertEqual(results[0].url, "https://115.com/s/swslzrw3nbi?password=8888")
        self.assertIn("大主宰", results[0].context)

    async def test_telegram_links_from_nearby_button_message_are_clicked_for_search_hit(self) -> None:
        class Button:
            text = "查看115链接"
            url = None
            button = None

        class Message:
            def __init__(self, message_id: int, text: str, buttons=None) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = buttons
                self.media = None

            async def click(self, row, col):
                return "链接：https://115.com/s/buttoncode?password=8888"

        class Client:
            async def get_messages(self, peer, ids):
                return [
                    Message(20, "电视剧：大主宰 (2023) S01E01-E80"),
                    Message(21, "点击查看资源", [[Button()]]),
                ]

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(Client(), Message(20, "电视剧：大主宰 (2023) S01E01-E80"), "telegram:test", "dialog-entity", ["大主宰"])

        self.assertEqual(results[0].url, "https://115.com/s/buttoncode?password=8888")
        self.assertIn("大主宰", results[0].context)

    async def test_telegram_button_click_reads_edited_message_after_callback(self) -> None:
        class Button:
            text = "查看资源"
            url = None
            button = None

        class Message:
            id = 33
            raw_text = "电视剧：大主宰 (2023) S01E01-E80"
            message = raw_text
            grouped_id = None
            peer_id = "channel"
            entities = []
            buttons = [[Button()]]
            media = None

            async def click(self, row, col):
                self.raw_text = "电视剧：大主宰 (2023) S01E01-E80\n链接：https://115.com/s/editedcode?password=8888"
                self.message = self.raw_text
                return object()

        class Client:
            async def get_messages(self, peer, ids):
                return message

        message = Message()
        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(Client(), message, "telegram:test", "dialog-entity", ["大主宰"])

        self.assertEqual(results[0].url, "https://115.com/s/editedcode?password=8888")

    async def test_telegram_button_external_page_link_is_parsed(self) -> None:
        class Button:
            text = "查看资源"
            url = "https://telegra.ph/drama-resource"
            button = None

        class Message:
            id = 34
            raw_text = "📺 善意的竞争 (2025)"
            message = raw_text
            grouped_id = None
            peer_id = "channel"
            entities = []
            buttons = [[Button()]]
            media = None

            async def click(self, row, col):
                return object()

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url):
                html = """
                <html><body>
                  <h1>善意的竞争 (2025)</h1>
                  <a href="https://115.com/s/twostep?password=8888">查看链接</a>
                </body></html>
                """
                return httpx.Response(200, text=html, request=httpx.Request("GET", url))

        adapter = TelegramClientAdapter()
        with patch("app.services.integrations.httpx.AsyncClient", FakeClient):
            results = await adapter._links_from_message(None, Message(), "telegram:test")

        self.assertEqual(results[0].url, "https://115.com/s/twostep?password=8888")
        self.assertIn("telegra.ph", results[0].context)

    async def test_telegram_text_url_external_page_link_is_parsed(self) -> None:
        class TextUrlEntity:
            url = "https://telegra.ph/resource-drama"

        class Message:
            id = 36
            raw_text = "📺电视剧：灿如繁星 (2026) S01E01-E08\n🔗链接：点击跳转"
            message = raw_text
            grouped_id = None
            peer_id = "channel"
            entities = [TextUrlEntity()]
            buttons = None
            media = None

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url):
                html = """
                <html><body>
                  <a href="https://115.com/s/swsslep63nbi?password=8888">115</a>
                </body></html>
                """
                return httpx.Response(200, text=html, request=httpx.Request("GET", url))

        adapter = TelegramClientAdapter()
        with patch("app.services.integrations.httpx.AsyncClient", FakeClient):
            results = await adapter._links_from_message(None, Message(), "telegram:test", match_queries=["灿如繁星"])

        self.assertEqual(results[0].url, "https://115.com/s/swsslep63nbi?password=8888")
        self.assertIn("灿如繁星", results[0].context)

    async def test_telegram_unrelated_buttons_are_not_clicked(self) -> None:
        class Button:
            text = "下一页"
            url = None
            button = None

        class Message:
            id = 35
            raw_text = "善意的竞争 (2025)"
            message = raw_text
            grouped_id = None
            peer_id = "channel"
            entities = []
            buttons = [[Button()]]
            media = None
            clicked = False

            async def click(self, row, col):
                self.clicked = True
                return "https://115.com/s/should-not-click?password=8888"

        message = Message()
        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(None, message, "telegram:test")

        self.assertEqual(results, [])
        self.assertFalse(message.clicked)

    async def test_telegram_nearby_unrelated_resource_is_not_joined(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def get_messages(self, peer, ids):
                return [
                    Message(30, "电视剧：大主宰 (2023) S01E01-E80"),
                    Message(31, "电视剧：英雄 (2006) S01E01-E23\n链接：https://115.com/s/hero?password=8888"),
                ]

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(Client(), Message(30, "电视剧：大主宰 (2023) S01E01-E80"), "telegram:test", "dialog-entity", ["大主宰"])

        self.assertEqual(results, [])

    async def test_telegram_message_text_reads_nested_dict_values(self) -> None:
        class Message:
            raw_text = ""
            message = ""
            entities = []
            buttons = None

            def to_dict(self):
                return {"media": {"webpage": {"description": "链接：https://115.com/s/nestedcode?password=8888"}}}

        adapter = TelegramClientAdapter()
        results = await adapter._links_from_message(None, Message(), "telegram:test")

        self.assertEqual(results[0].url, "https://115.com/s/nestedcode?password=8888")

    def test_telegram_dialog_candidates_accept_plain_and_marked_channel_ids(self) -> None:
        candidates = TelegramClientAdapter()._dialog_candidates("2330381084")

        self.assertIn(2330381084, candidates)
        self.assertIn(-1002330381084, candidates)

    async def test_telegram_fast_search_returns_first_direct_hit(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def is_user_authorized(self):
                return True

            async def get_messages(self, peer, **kwargs):
                if kwargs.get("search"):
                    return [Message(10, "将夜 2026 S01E01 1080p https://115.com/s/fastlink?password=8888")]
                return []

        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=Client())), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001"},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history_fast("将夜 2026", [])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://115.com/s/fastlink?password=8888")

    async def test_telegram_history_search_respects_internal_time_budget(self) -> None:
        class SlowClient:
            async def is_user_authorized(self):
                return True

            async def iter_messages(self, *args, **kwargs):
                await asyncio.sleep(0.2)
                if False:
                    yield None

        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=SlowClient())), patch.object(
            adapter,
            "_config",
            return_value={
                "api_id": "1",
                "api_hash": "hash",
                "sources": "-1001",
                "history_timeout": 0.12,
                "history_query_timeout": 0.05,
                "history_fallback_timeout": 0.05,
                "history_limit": 80,
            },
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            started = asyncio.get_running_loop().time()
            results = await adapter.search_history("Drama 2026", [])
            elapsed = asyncio.get_running_loop().time() - started

        self.assertEqual(results, [])
        self.assertLess(elapsed, 0.6)

    async def test_telegram_history_search_extracts_nearby_link_message(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def is_user_authorized(self):
                return True

            async def iter_messages(self, *args, **kwargs):
                if kwargs.get("search"):
                    yield Message(50, "将夜 2026 S01E01 1080p")

            async def get_messages(self, peer, ids):
                return [
                    Message(50, "将夜 2026 S01E01 1080p"),
                    Message(51, "链接：https://115.com/s/jiangye2026?password=8888"),
                ]

        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=Client())), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001", "history_timeout": 1},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history("将夜 2026", [])

        self.assertEqual(results[0].url, "https://115.com/s/jiangye2026?password=8888")
        self.assertIn("将夜", results[0].context)

    async def test_telegram_history_search_falls_back_to_configured_recent_limit(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            def __init__(self) -> None:
                self.recent_limit = 0
                self.search_calls = 0

            async def is_user_authorized(self):
                return True

            async def iter_messages(self, *args, **kwargs):
                if kwargs.get("search"):
                    self.search_calls += 1
                    if False:
                        yield None
                    return
                self.recent_limit = kwargs.get("limit")
                for index in range(1, 301):
                    text = f"无关消息 {index}"
                    if index == 299:
                        text = "将夜 2026 S01E01 1080p"
                    elif index == 300:
                        text = "链接：https://115.com/s/recent300?password=8888"
                    yield Message(index, text)

            async def get_messages(self, peer, ids):
                raise AssertionError("recent scan already has nearby link text")

        client = Client()
        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=client)), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001", "history_limit": 300, "history_timeout": 2},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history("将夜 2026", [])

        self.assertEqual(client.recent_limit, 300)
        self.assertEqual(client.search_calls, 0)
        self.assertEqual(results[0].url, "https://115.com/s/recent300?password=8888")

    async def test_telegram_recent_scan_falls_back_to_iter_messages_when_get_messages_empty(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def is_user_authorized(self):
                return True

            async def get_messages(self, *args, **kwargs):
                return []

            async def iter_messages(self, *args, **kwargs):
                if kwargs.get("search"):
                    return
                yield Message(1, "灿如繁星 2026 S01E01-E08")
                yield Message(2, "链接：https://115.com/s/fallbackiter?password=8888")

        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=Client())), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001", "history_limit": 20, "history_timeout": 2},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history("灿如繁星 2026", [])

        self.assertEqual(results[0].url, "https://115.com/s/fallbackiter?password=8888")

    async def test_telegram_recent_scan_returns_link_windows_when_title_search_misses(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            async def is_user_authorized(self):
                return True

            async def iter_messages(self, *args, **kwargs):
                if kwargs.get("search"):
                    if False:
                        yield None
                    return
                yield Message(1, "频道资源更新")
                yield Message(2, "链接：https://115.com/s/windowcode?password=8888")

            async def get_messages(self, peer, ids):
                return []

        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=Client())), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001", "history_limit": 20, "history_timeout": 2},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history("灿如繁星 2026", [])

        self.assertEqual(results[0].url, "https://115.com/s/windowcode?password=8888")

    async def test_telegram_recent_scan_skips_title_only_messages_without_link_hint(self) -> None:
        class Message:
            def __init__(self, message_id: int, text: str) -> None:
                self.id = message_id
                self.raw_text = text
                self.message = text
                self.grouped_id = None
                self.peer_id = "channel"
                self.entities = []
                self.buttons = None
                self.media = None

        class Client:
            def __init__(self) -> None:
                self.get_messages_calls = 0

            async def is_user_authorized(self):
                return True

            async def iter_messages(self, *args, **kwargs):
                if kwargs.get("search"):
                    if False:
                        yield None
                    return
                for index in range(1, 301):
                    yield Message(index, f"将夜 2026 花絮 {index}")

            async def get_messages(self, peer, ids):
                self.get_messages_calls += 1
                return []

        client = Client()
        adapter = TelegramClientAdapter()
        with patch.object(adapter, "client", new=AsyncMock(return_value=client)), patch.object(
            adapter,
            "_config",
            return_value={"api_id": "1", "api_hash": "hash", "sources": "-1001", "history_limit": 300, "history_timeout": 2},
        ), patch.object(adapter, "_resolve_dialogs", new=AsyncMock(return_value=[{"entity": "dialog", "source": "-1001", "canonical": "-1001"}])):
            results = await adapter.search_history("将夜 2026", [])

        self.assertEqual(results, [])
        self.assertEqual(client.get_messages_calls, 0)

    def test_telegram_configured_sources_accept_list_and_legacy_string(self) -> None:
        adapter = TelegramClientAdapter()

        self.assertEqual(adapter._configured_sources({"sources": ["-1001", {"source": "-1002"}]}), ["-1001", "-1002"])
        self.assertEqual(adapter._configured_sources({"sources": "['-1001', '-1002']"}), ["-1001", "-1002"])

    def test_115_link_context_keeps_title_lines_for_multi_link_messages(self) -> None:
        link = "https://115.com/s/swssxf43nbi?password=8888"
        text = "\n".join(
            [
                "电视剧：爱情有烟火 (2026)",
                "S01E01-E36",
                "TMDB ID: 230311",
                "质量：[4K] [HDR10]",
                "链接：https://115.com/s/old?password=1111",
                "电视剧：爱情有烟火 (2026)",
                "S01E33-E36",
                f"链接：{link}",
            ]
        )
        context = context_for_115_link(text, link, 2)

        self.assertIn("爱情有烟火", context)
        self.assertIn("S01E33-E36", context)
        self.assertNotIn("old?password", context)

    def test_115_link_context_keeps_movie_title_when_link_after_long_intro(self) -> None:
        link = "https://115cdn.com/s/swslijs3nbi?password=8888"
        text = "\n".join(
            [
                "🎬 电影：流感 (2013) 💎REMUX 1080P",
                "⭐ 评分：7.5",
                "🎥 类型：动作，科幻，惊悚",
                "🍿 TMDB ID：200085",
                "💾 大小：27.04GB",
                "📼 质量：1080P / BluRay Remux / H.264",
                "🏷 标签：#流感 #电影 #动作 #科幻 #Remux",
                "📖 简介：",
                "一群东南亚偷渡客历经艰险来到韩国。",
                "病毒迅速蔓延城市的各个角落。",
                "许多人在不知不觉间被感染。",
                "城市陷入混乱。",
                "更多简介文本 1",
                "更多简介文本 2",
                "更多简介文本 3",
                f"链接：{link}",
                "电影：其它影片 (2024)",
                "链接：https://115cdn.com/s/other?password=8888",
            ]
        )

        context = context_for_115_link(text, link, 2)
        result = SearchResult(title=context[:120], url=link, source="telegram:test", context=context)
        subscription = {"title": "流感", "media_type": "movie", "tmdb_id": 200085, "release_year": 2013, "keywords": ["流感"]}

        self.assertTrue(context.startswith("🎬 电影：流感 (2013)"))
        self.assertIn("TMDB ID", context)
        self.assertTrue(result_matches_subscription(subscription, result))

    async def test_torznab_parse_and_match(self) -> None:
        adapter = RssTorznabAdapter()
        feed = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>南部档案 S01E01 1080p</title>
              <enclosure url="magnet:?xt=urn:btih:test123" />
              <description>南部档案 1080p</description>
            </item>
          </channel>
        </rss>"""
        source = {"name": "test", "type": "torznab", "url": "https://example.com/?t=search&q={query}", "enabled": True}
        results = adapter._parse_feed(source, feed)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "magnet:?xt=urn:btih:test123")
        subscription = {"title": "南部档案", "keywords": ["1080p"], "tmdb_id": None}
        self.assertTrue(result_matches_subscription(subscription, results[0]))

    async def test_source_query_template(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "test", "type": "torznab", "url": "https://example.com/search/{query}", "enabled": True}
        url = adapter._source_url(source, "南部档案")
        self.assertIn("%E5%8D%97%E9%83%A8%E6%A1%A3%E6%A1%88", url)
        self.assertNotIn("{query}", url)

    def test_site_plugin_type_normalizes_legacy_magnet_web(self) -> None:
        adapter = RssTorznabAdapter()

        self.assertEqual(adapter._source_type({"type": "site_plugin"}), "site_plugin")
        self.assertEqual(adapter._source_type({"type": "magnet_web"}), "site_plugin")
        self.assertEqual(adapter._site_plugin_id({"type": "site_plugin", "plugin": "bt1207"}), "bt1207")
        self.assertEqual(adapter._site_plugin_id({"type": "magnet_web", "url": "https://example.com/"}), "generic_magnet")

    def test_sources_sorted_by_priority_desc(self) -> None:
        adapter = RssTorznabAdapter()
        config = {
            "sources": [
                {"name": "低", "url": "https://low.example/rss", "priority": 1, "enabled": True},
                {"name": "高", "url": "https://high.example/rss", "priority": 10, "enabled": True},
                {"name": "中", "url": "https://mid.example/rss", "priority": 5, "enabled": True},
            ]
        }

        with patch("app.services.integrations.get_setting", return_value=config):
            names = [source["name"] for source in adapter._sources()]

        self.assertEqual(names[:3], ["高", "中", "低"])
        self.assertIn("BT1207", names)
        self.assertIn("QMP4 / 七味", names)

    def test_builtin_sources_are_available_without_manual_config(self) -> None:
        adapter = RssTorznabAdapter()

        with patch("app.services.integrations.get_setting", return_value={"sources": []}):
            sources = adapter._sources()

        names = [source["name"] for source in sources]
        self.assertIn("BT1207", names)
        self.assertIn("QMP4 / 七味", names)
        self.assertTrue(all(source.get("_builtin") for source in sources))
        self.assertEqual(adapter._source_url(next(source for source in sources if source["name"] == "BT1207"), "爱丽丝 2020"), "https://bt1207to.cc/search?keyword=%E7%88%B1%E4%B8%BD%E4%B8%9D+2020")

    def test_builtin_sources_do_not_duplicate_existing_site_plugins(self) -> None:
        adapter = RssTorznabAdapter()
        config = {
            "sources": [
                {"name": "我的 BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True},
                {"name": "七味备用", "type": "site_plugin", "url": "https://www.qmp4.com/", "enabled": True},
            ]
        }

        with patch("app.services.integrations.get_setting", return_value=config):
            sources = adapter._sources()

        plugin_ids = [adapter._site_plugin_id(source) for source in sources if adapter._source_type(source) == "site_plugin"]
        self.assertEqual(plugin_ids.count("bt1207"), 1)
        self.assertEqual(plugin_ids.count("qmp4"), 1)

    def test_builtin_sources_apply_saved_overrides(self) -> None:
        adapter = RssTorznabAdapter()
        config = {
            "sources": [],
            "builtin_sources": {
                "builtin_bt1207": {
                    "url": "https://bt1207.example/",
                    "use_proxy": True,
                    "priority": 20,
                    "refresh_interval": 15,
                    "keywords": "1080p",
                    "quality": "4K",
                    "test_query": "爱丽丝",
                }
            },
        }

        with patch("app.services.integrations.get_setting", return_value=config):
            source = next(source for source in adapter._sources() if source["id"] == "builtin_bt1207")

        self.assertEqual(source["url"], "https://bt1207.example/")
        self.assertTrue(source["use_proxy"])
        self.assertEqual(source["priority"], 20)
        self.assertEqual(source["refresh_interval"], 15)
        self.assertEqual(source["keywords"], "1080p")
        self.assertEqual(source["quality"], "4K")
        self.assertEqual(source["test_query"], "爱丽丝")

    def test_builtin_sources_can_be_disabled(self) -> None:
        adapter = RssTorznabAdapter()
        config = {"sources": [], "builtin_sources": {"builtin_bt1207": {"enabled": False}}}

        with patch("app.services.integrations.get_setting", return_value=config):
            sources = adapter._sources()

        names = [source["name"] for source in sources]
        self.assertNotIn("BT1207", names)
        self.assertIn("QMP4 / 七味", names)

    async def test_priority_search_stops_before_lower_sources_after_match(self) -> None:
        adapter = RssTorznabAdapter()
        config = {
            "sources": [
                {"name": "低", "url": "https://low.example/rss", "priority": 1, "enabled": True},
                {"name": "高", "url": "https://high.example/rss", "priority": 10, "enabled": True},
                {"name": "中", "url": "https://mid.example/rss", "priority": 5, "enabled": True},
            ]
        }
        calls: list[str] = []

        async def fake_fetch(source: dict, queries: list[str]) -> list[SearchResult]:
            calls.append(source["name"])
            if source["name"] == "高":
                return [SearchResult(title="南部档案 S01E01 1080p", url="magnet:?xt=urn:btih:high", source="magnet_web:高", priority=10)]
            return [SearchResult(title="南部档案 S01E01 1080p", url=f"magnet:?xt=urn:btih:{source['name']}", source=f"magnet_web:{source['name']}")]

        with patch("app.services.integrations.get_setting", return_value=config):
            with patch.object(adapter, "_fetch_source_for_queries", side_effect=fake_fetch):
                groups = await adapter.search_history_by_priority_until_match(
                    "南部档案",
                    ["1080p"],
                    lambda result: "南部档案" in result.title,
                )

        self.assertEqual(calls, ["高"])
        self.assertEqual([group["source"]["name"] for group in groups], ["高"])

    async def test_priority_search_continues_when_matcher_fails_for_one_result(self) -> None:
        adapter = RssTorznabAdapter()
        config = {
            "sources": [
                {"name": "坏源", "url": "https://bad.example/rss", "priority": 10, "enabled": True},
                {"name": "好源", "url": "https://good.example/rss", "priority": 5, "enabled": True},
            ]
        }
        calls: list[str] = []

        async def fake_fetch(source: dict, queries: list[str]) -> list[SearchResult]:
            calls.append(source["name"])
            return [
                SearchResult(
                    title=f"{source['name']} 南部档案 S01E21 1080p",
                    url=f"magnet:?xt=urn:btih:{source['name']}",
                    source=f"site_plugin:{source['name']}",
                )
            ]

        def matcher(result: SearchResult) -> bool:
            if "坏源" in result.source:
                raise RuntimeError("bad matcher")
            return "好源" in result.source

        with patch("app.services.integrations.get_setting", return_value=config):
            with patch.object(adapter, "_fetch_source_for_queries", side_effect=fake_fetch):
                groups = await adapter.search_history_by_priority_until_match("南部档案", ["1080p"], matcher)

        self.assertEqual(calls, ["坏源", "好源"])
        self.assertEqual([group["source"]["name"] for group in groups], ["坏源", "好源"])


    async def test_source_query_results_are_cached(self) -> None:
        adapter = RssTorznabAdapter()
        adapter._search_cache.clear()
        source = {"name": "Cache", "url": "https://cache.example/rss?q={query}", "enabled": True}
        calls = 0

        async def fake_fetch(source_arg: dict, query: str | None, client=None) -> list[SearchResult]:
            nonlocal calls
            calls += 1
            return [SearchResult(title=f"Cache {query}", url=f"magnet:?xt=urn:btih:{calls:032d}", source="rss:Cache")]

        with patch.object(adapter, "_fetch_source", side_effect=fake_fetch):
            first = await adapter._fetch_source_for_queries(source, ["Drama"])
            second = await adapter._fetch_source_for_queries(source, ["Drama"])

        self.assertEqual(calls, 1)
        self.assertEqual(first[0].url, second[0].url)

    async def test_magnet_web_source_url_template(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "樱花动漫", "type": "site_plugin", "plugin": "generic_magnet", "url": "https://yhdm33.com/s/{query}.html", "enabled": True}
        url = adapter._source_url(source, "Fate strange Fake")
        self.assertEqual(url, "https://yhdm33.com/s/Fate%20strange%20Fake.html")

    async def test_magnet_web_root_url_uses_common_search_path(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "樱花动漫", "type": "site_plugin", "plugin": "generic_magnet", "url": "https://yhdm33.com/", "enabled": True}
        url = adapter._source_url(source, "斗罗大陆")
        self.assertEqual(url, "https://yhdm33.com/s/%E6%96%97%E7%BD%97%E5%A4%A7%E9%99%86.html")

    async def test_bt1207_root_url_uses_keyword_search(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "BT1207", "type": "site_plugin", "plugin": "bt1207", "url": "https://bt1207to.cc/", "enabled": True}
        url = adapter._source_url(source, "Game of Thrones")
        self.assertEqual(url, "https://bt1207to.cc/search?keyword=Game+of+Thrones")

    async def test_qmp4_root_url_uses_ajax_suggest_search(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "QMP4", "type": "site_plugin", "plugin": "qmp4", "url": "https://www.qmp4.com/", "enabled": True}
        url = adapter._source_url(source, "爱丽丝 2020")
        self.assertEqual(url, "https://www.qmp4.com/index.php/ajax/suggest?mid=1&wd=%E7%88%B1%E4%B8%BD%E4%B8%9D+2020")
        self.assertEqual(adapter._site_plugin_id({"type": "site_plugin", "url": "https://www.qmp4.com/"}), "qmp4")
        self.assertEqual(adapter._source_queries(source, ["爱丽丝 2020 1080p"]), ["爱丽丝 2020 1080p", "爱丽丝 1080p", "爱丽丝"])

    def test_magnet_web_challenge_detection(self) -> None:
        adapter = RssTorznabAdapter()
        html = "<title>Recaptcha - Bot Challenge!</title><form action='/anti/recaptcha/v4/verify'></form>"
        self.assertTrue(adapter._is_magnet_web_challenge("https://bt1207to.cc/recaptcha/v4/challenge", html))
        qmp4_html = "<title>系统安全验证</title><script>MAC.Ajax('/index.php/ajax/verify_check?type=search')</script>"
        self.assertTrue(adapter._is_magnet_web_challenge("https://www.qmp4.com/vs/-------------.html?wd=test", qmp4_html))

    def test_bt1207_search_home_fallback_detection(self) -> None:
        adapter = RssTorznabAdapter()
        html = "<html><head><title>BT1207 - 好用的磁力链接搜索引擎</title></head><body><form action='/search'></form></body></html>"
        self.assertTrue(
            adapter._is_bt1207_search_home_fallback(
                "https://bt1207to.cc/search?keyword=%E7%88%B1%E4%B8%BD%E4%B8%9D",
                "https://bt1207to.cc/",
                html,
            )
        )

    async def test_bt1207_year_filter_does_not_drop_detail_candidates(self) -> None:
        adapter = RssTorznabAdapter()
        search_html = """
        <html><body>
          <a href="/detail/06B46/Fy4bsmTLoWCPJKS1XcYt85jxSy0">宝莱坞机器人之恋</a>
          <a href="/detail/F55D4/j6qMXb3d2GQw17dpwF-mnmlruHi">[2011.03.22] 宝莱坞机器人之恋</a>
        </body></html>
        """
        detail_urls = adapter._magnet_web_detail_urls("https://bt1207to.cc/search?keyword=%E5%AE%9D%E8%8E%B1%E5%9D%9E%E6%9C%BA%E5%99%A8%E4%BA%BA%E4%B9%8B%E6%81%8B%202010", search_html, 2010)

        self.assertTrue(detail_urls)
        self.assertIn("https://bt1207to.cc/detail/06B46/Fy4bsmTLoWCPJKS1XcYt85jxSy0", detail_urls)

    async def test_magnet_web_detail_urls_and_page_parse(self) -> None:
        adapter = RssTorznabAdapter()
        search_html = """
        <html><body>
          <a href="/movie/71679796.html">Fate strange Fake</a>
          <a href="/style/app.css">style</a>
        </body></html>
        """
        detail_urls = adapter._magnet_web_detail_urls("https://yhdm33.com/s/Fate%20strange%20Fake.html", search_html)
        self.assertEqual(detail_urls, ["https://yhdm33.com/movie/71679796.html"])

        detail_html = """
        <html><head><title>Fate strange Fake 下载</title></head><body>
          <a class="download-title" href="thunder://example">ANi Fate strange Fake - 01 1080P WEB-DL</a>
          <a class="copylink" alt="magnet:?xt=urn:btih:abc123&amp;dn=Fate">复制链接</a>
        </body></html>
        """
        source = {"name": "樱花动漫", "type": "site_plugin", "plugin": "generic_magnet", "url": "https://yhdm33.com/s/{query}.html", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://yhdm33.com/movie/71679796.html", detail_html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "magnet:?xt=urn:btih:abc123&dn=Fate")
        self.assertIn("Fate strange Fake", results[0].context)
        self.assertEqual(results[0].source, "site_plugin:樱花动漫")

    async def test_qmp4_suggest_json_fetches_detail_pages(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "QMP4", "type": "site_plugin", "plugin": "qmp4", "url": "https://www.qmp4.com/", "enabled": True}
        suggest_json = '{"code":1,"list":[{"id":502910,"name":"爱丽丝与史蒂夫","en":"Alice and Steve"}]}'
        detail_html = """
        <html><head><title>爱丽丝与史蒂夫在线观看</title></head><body>
          <div class="download-row">
            <a class="title">爱丽丝与史蒂夫.全集打包.1080p.HD中英双字.mp4</a>
            <a href="magnet:?xt=urn:btih:cbc239c40c39ee5e438c5fef69bbfb1922f2da2d&dn=Alice">磁力下载</a>
          </div>
        </body></html>
        """
        with patch.object(adapter, "_fetch_magnet_web_detail", new=AsyncMock(return_value=("https://www.qmp4.com/mv/502910.html", detail_html))):
            results = await adapter._parse_qmp4_source(source, "https://www.qmp4.com/index.php/ajax/suggest?mid=1&wd=%E7%88%B1%E4%B8%BD%E4%B8%9D", suggest_json, None)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "magnet:?xt=urn:btih:cbc239c40c39ee5e438c5fef69bbfb1922f2da2d&dn=Alice")
        self.assertIn("爱丽丝与史蒂夫", results[0].context)
        self.assertEqual(results[0].source, "site_plugin:QMP4")

    async def test_qmp4_detail_keeps_unescaped_magnet_with_spaces(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "QMP4 / 七味", "type": "site_plugin", "plugin": "qmp4", "url": "https://www.qmp4.com/", "enabled": True}
        suggest_json = '{"code":1,"list":[{"id":499922,"name":"火遮眼","en":"huozheyan"}]}'
        detail_html = """
        <html><head><title>火遮眼在线观看-火遮眼迅雷下载 - 七味</title></head><body>
          <li class="down-list2">
            <a href="magnet:?xt=urn:btih:71be60c1be2b680d50e4c7e8910095f67fded89b&dn=UIndex    -    The.Furious.2026.1080p.CAM.x264.ENG.AAC-EaZy" title="UIndex - The.Furious.2026.1080p.CAM.x264.ENG.AAC-EaZy[5.17G]">UIndex - The.Furious.2026.1080p.CAM.x264.ENG.AAC-EaZy[5.17G]</a>
          </li>
        </body></html>
        """

        with patch.object(adapter, "_fetch_magnet_web_detail", new=AsyncMock(return_value=("https://www.qmp4.com/mv/499922.html", detail_html))):
            results = await adapter._parse_qmp4_source(source, "https://www.qmp4.com/index.php/ajax/suggest?mid=1&wd=%E7%81%AB%E9%81%AE%E7%9C%BC", suggest_json, None)

        self.assertEqual(len(results), 1)
        self.assertIn("The.Furious.2026", results[0].url)
        self.assertIn("火遮眼", results[0].context)
        self.assertEqual(results[0].source, "site_plugin:QMP4 / 七味")

    async def test_magnet_web_detail_urls_prefer_matching_year(self) -> None:
        adapter = RssTorznabAdapter()
        search_html = """
        <html><body>
          <div class="result"><a href="/movie/2015.html">生化危机战</a> <span>(2015)</span></div>
          <div class="result"><a href="/movie/2022.html">生化危机 Resident Evil</a> <span>(2022)</span></div>
          <div class="result"><a href="/movie/2002.html">Resident Evil</a> <span>(2002)</span></div>
        </body></html>
        """
        detail_urls = adapter._magnet_web_detail_urls("https://example.com/s/%E7%94%9F%E5%8C%96%E5%8D%B1%E6%9C%BA%202015.html", search_html, 2015)
        self.assertEqual(detail_urls, ["https://example.com/movie/2015.html"])

    async def test_magnet_web_year_filter_does_not_bleed_between_result_cards(self) -> None:
        adapter = RssTorznabAdapter()
        search_html = """
        <html><body>
          <div class="result"><a href="/movie/2022.html">生化危机 Resident Evil</a> <span>(2022)</span></div>
          <div class="result"><a href="/movie/2002.html">Resident Evil</a> <span>(2002)</span></div>
        </body></html>
        """
        detail_urls = adapter._magnet_web_detail_urls("https://example.com/s/%E7%94%9F%E5%8C%96%E5%8D%B1%E6%9C%BA%202015.html", search_html, 2015)
        self.assertEqual(detail_urls, [])

    async def test_magnet_web_duplicate_detail_link_keeps_year_from_title_card(self) -> None:
        adapter = RssTorznabAdapter()
        search_html = """
        <html><body>
          <div class="result">
            <div class="poster"><a href="/movie/2015.html"><img alt="生化危机战" /></a></div>
            <div class="meta"><h2><a href="/movie/2015.html">生化危机战</a><i>(2015)</i></h2></div>
          </div>
          <div class="result">
            <div class="poster"><a href="/movie/2022.html"><img alt="生化危机" /></a></div>
            <div class="meta"><h2><a href="/movie/2022.html">生化危机 Resident Evil</a><i>(2022)</i></h2></div>
          </div>
        </body></html>
        """

        detail_urls = adapter._magnet_web_detail_urls("https://example.com/s/%E7%94%9F%E5%8C%96%E5%8D%B1%E6%9C%BA%E6%88%98%202015.html", search_html, 2015)

        self.assertEqual(detail_urls, ["https://example.com/movie/2015.html"])

    async def test_magnet_web_page_parse_keeps_each_magnet_context_separate(self) -> None:
        adapter = RssTorznabAdapter()
        detail_html = """
        <html><body>
          <div class="download-row">
            <a class="title">生化危机战 (2015) 1080p WEB-DL</a>
            <a class="copylink" alt="magnet:?xt=urn:btih:aaa111">复制链接</a>
          </div>
          <div class="download-row">
            <a class="title">生化危机 Resident Evil (2022) 1080p WEB-DL</a>
            <a class="copylink" alt="magnet:?xt=urn:btih:bbb222">复制链接</a>
          </div>
        </body></html>
        """
        source = {"name": "磁力站", "type": "magnet_web", "url": "https://example.com/s/{query}.html", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://example.com/movie/2015.html", detail_html)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "生化危机战 (2015) 1080p WEB-DL")
        self.assertNotIn("2022", results[0].context)
        self.assertEqual(results[1].title, "生化危机 Resident Evil (2022) 1080p WEB-DL")

    async def test_magnet_web_detail_context_includes_search_card_hint(self) -> None:
        adapter = RssTorznabAdapter()
        detail_html = """
        <html><head><title>下载页面</title></head><body>
          <div class="download-row">
            <a class="title">生化危机战 1080p WEB-DL</a>
            <a class="copylink" alt="magnet:?xt=urn:btih:aaa111">复制链接</a>
          </div>
        </body></html>
        """
        source = {"name": "磁力站", "type": "magnet_web", "url": "https://example.com/s/{query}.html", "enabled": True}

        results = adapter._parse_magnet_web_page(source, "https://example.com/movie/2015.html", detail_html, "生化危机战 (2015)")

        subscription_2015 = {"title": "生化危机战", "media_type": "movie", "tmdb_id": 0, "release_year": 2015, "keywords": ["生化危机战"]}
        subscription_2022 = {"title": "生化危机战", "media_type": "movie", "tmdb_id": 0, "release_year": 2022, "keywords": ["生化危机战"]}
        self.assertTrue(result_matches_subscription(subscription_2015, results[0]))
        self.assertFalse(result_matches_subscription(subscription_2022, results[0]))

    async def test_test_source_returns_status_payload(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "test", "type": "rss", "url": "https://example.com/feed", "enabled": True}
        result = await adapter.test_source(source)
        self.assertIn("ok", result)
        self.assertIn("source", result)

    def test_hdhive_orders_free_resources_before_points_resources(self) -> None:
        items = [
            {"href": "https://hdhive.com/resource/115/paid", "text": "HDHive paid 1080p 需要 5 积分解锁 80GB"},
            {"href": "https://hdhive.com/resource/115/free", "text": "HDHive free 1080p 已解锁 20GB"},
            {"href": "https://hdhive.com/resource/115/dead", "text": "HDHive dead 疑似失效 已解锁 100GB"},
        ]

        ordered = order_hdhive_candidates(extract_hdhive_resource_candidates(items), max_points=10)

        self.assertEqual([item.href.rsplit("/", 1)[-1] for item in ordered], ["free", "paid"])

    def test_hdhive_filters_points_above_threshold(self) -> None:
        items = [
            {"href": "https://hdhive.com/resource/115/paid", "text": "HDHive paid 需要 20 积分解锁"},
            {"href": "https://hdhive.com/resource/115/unknown", "text": "HDHive unknown 需要积分解锁"},
        ]

        ordered = order_hdhive_candidates(extract_hdhive_resource_candidates(items), max_points=10)

        self.assertEqual(ordered, [])

    async def test_hdhive_source_uses_tmdb_context(self) -> None:
        adapter = RssTorznabAdapter()
        captured: dict[str, object] = {}

        async def fake_search(media_type, tmdb_id, context):
            captured.update({"media_type": media_type, "tmdb_id": tmdb_id, "context": context})
            return [SearchResult(title="HDHive", url="https://115cdn.com/s/test?password=1234", source="site_plugin:HDHive")]

        source = {"name": "HDHive", "type": "site_plugin", "plugin": "hdhive", "url": "https://hdhive.com/", "enabled": True}
        with patch("app.services.sources.rss_torznab_hdhive.HdhiveBrowserClient.search_tmdb", side_effect=fake_search):
            results = await adapter._fetch_hdhive_source(source, "铁梨花", {"media_type": "tv", "tmdb_id": 86344, "title": "铁梨花"})

        self.assertEqual(results[0].url, "https://115cdn.com/s/test?password=1234")
        self.assertEqual(captured["media_type"], "tv")
        self.assertEqual(captured["tmdb_id"], 86344)


if __name__ == "__main__":
    unittest.main()
