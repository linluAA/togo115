from __future__ import annotations

import unittest

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
