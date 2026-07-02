import unittest
from unittest.mock import patch

from app.services.integrations import RssTorznabAdapter, SearchResult, TelegramClientAdapter, context_for_115_link, extract_download_links
from app.services.subscription import result_matches_subscription


class RssTorznabTest(unittest.IsolatedAsyncioTestCase):
    def test_extract_download_links_includes_magnet_and_torrent(self) -> None:
        text = "magnet:?xt=urn:btih:abc123 http://example.com/file.torrent 115cdn.com/s/abc123"
        links = extract_download_links(text)
        self.assertIn("magnet:?xt=urn:btih:abc123", links)
        self.assertIn("http://example.com/file.torrent", links)
        self.assertIn("https://115cdn.com/s/abc123", links)

    def test_extract_115_links_accepts_wrapped_share_url(self) -> None:
        text = "链接：https://115.com/s\n/swssxf43nbi?password=8888"
        links = extract_download_links(text)

        self.assertIn("https://115.com/s/swssxf43nbi?password=8888", links)

    def test_telegram_dialog_candidates_accept_plain_and_marked_channel_ids(self) -> None:
        candidates = TelegramClientAdapter()._dialog_candidates("2330381084")

        self.assertIn(2330381084, candidates)
        self.assertIn(-1002330381084, candidates)

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

        self.assertEqual(names, ["高", "中", "低"])

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

    async def test_magnet_web_source_url_template(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "樱花动漫", "type": "magnet_web", "url": "https://yhdm33.com/s/{query}.html", "enabled": True}
        url = adapter._source_url(source, "Fate strange Fake")
        self.assertEqual(url, "https://yhdm33.com/s/Fate%20strange%20Fake.html")

    async def test_magnet_web_root_url_uses_common_search_path(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "樱花动漫", "type": "magnet_web", "url": "https://yhdm33.com/", "enabled": True}
        url = adapter._source_url(source, "斗罗大陆")
        self.assertEqual(url, "https://yhdm33.com/s/%E6%96%97%E7%BD%97%E5%A4%A7%E9%99%86.html")

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
        source = {"name": "樱花动漫", "type": "magnet_web", "url": "https://yhdm33.com/s/{query}.html", "enabled": True}
        results = adapter._parse_magnet_web_page(source, "https://yhdm33.com/movie/71679796.html", detail_html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "magnet:?xt=urn:btih:abc123&dn=Fate")
        self.assertIn("Fate strange Fake", results[0].context)
        self.assertEqual(results[0].source, "magnet_web:樱花动漫")

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


if __name__ == "__main__":
    unittest.main()
