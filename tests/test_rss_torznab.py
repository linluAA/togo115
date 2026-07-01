import unittest

from app.services.integrations import RssTorznabAdapter, SearchResult, extract_download_links
from app.services.subscription import result_matches_subscription


class RssTorznabTest(unittest.IsolatedAsyncioTestCase):
    def test_extract_download_links_includes_magnet_and_torrent(self) -> None:
        text = "magnet:?xt=urn:btih:abc123 http://example.com/file.torrent 115cdn.com/s/abc123"
        links = extract_download_links(text)
        self.assertIn("magnet:?xt=urn:btih:abc123", links)
        self.assertIn("http://example.com/file.torrent", links)

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

    async def test_test_source_returns_status_payload(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "test", "type": "rss", "url": "https://example.com/feed", "enabled": True}
        result = await adapter.test_source(source)
        self.assertIn("ok", result)
        self.assertIn("source", result)


if __name__ == "__main__":
    unittest.main()
