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

    async def test_test_source_returns_status_payload(self) -> None:
        adapter = RssTorznabAdapter()
        source = {"name": "test", "type": "rss", "url": "https://example.com/feed", "enabled": True}
        result = await adapter.test_source(source)
        self.assertIn("ok", result)
        self.assertIn("source", result)


if __name__ == "__main__":
    unittest.main()
