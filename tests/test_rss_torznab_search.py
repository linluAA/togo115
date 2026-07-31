from __future__ import annotations

import unittest

import httpx

from app.services.sources.rss.fetch_source import _fetch_error_payload
from app.services.sources.rss.search import RssTorznabSearchMixin
from app.services.types import SearchResult


class RssSearchHarness(RssTorznabSearchMixin):
    pass


class RssTorznabSearchMixinTest(unittest.TestCase):
    def test_source_filters_require_all_keywords_and_any_quality(self) -> None:
        mixin = RssSearchHarness()
        source = {"keywords": "南部档案,1080p", "quality": "2160p,web-dl"}

        self.assertTrue(mixin._source_matches_filters(source, "南部档案 S01E01 1080p WEB-DL"))
        self.assertFalse(mixin._source_matches_filters(source, "南部档案 S01E01 WEB-DL"))
        self.assertFalse(mixin._source_matches_filters(source, "南部档案 S01E01 1080p HDTV"))

    def test_dedupe_results_uses_source_and_download_key(self) -> None:
        mixin = RssSearchHarness()
        results = [
            SearchResult(title="A", url="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&dn=1", source="site:a"),
            SearchResult(title="B", url="magnet:?dn=2&xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site:a"),
            SearchResult(title="C", url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site:b"),
        ]

        deduped = mixin._dedupe_results(results)

        self.assertEqual([item.title for item in deduped], ["A", "C"])

    def test_http_status_error_payload_is_compact(self) -> None:
        request = httpx.Request("GET", "https://bt1207to.cc/search?keyword=%E9%87%91%E7%89%B9%E5%8A%A1")
        response = httpx.Response(503, request=request)
        exc = httpx.HTTPStatusError("Server error '503 Service Unavailable' for url", request=request, response=response)

        payload = _fetch_error_payload("BT1207", "https://bt1207to.cc/", exc)

        self.assertEqual(payload["source"], "BT1207")
        self.assertEqual(payload["status_code"], 503)
        self.assertEqual(payload["error_type"], "HTTPStatusError")
        self.assertEqual(payload["error"], "HTTP 503：订阅源临时不可用或触发站点限流")
        self.assertNotIn("developer.mozilla.org", payload["error"])
