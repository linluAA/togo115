from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.magnet import (
    _bot_title_or_alias_matches,
    _cached_magnet_search,
    _fast_magnet_queries,
    _fast_magnet_query_batches,
    _fast_source_options,
    _magnet_search_cache,
    _fetch_priority_sources,
    _fetch_priority_sources_until_ranked,
    _rank_magnet_results,
    _resource_size,
    _store_magnet_search_cache,
    magnet_results_reply,
    magnet_results_reply_markup,
    search_magnets_for_tmdb,
)


class TelegramBotMagnetSearchTest(unittest.TestCase):
    def test_magnet_pick_buttons_are_single_horizontal_row(self) -> None:
        results = [
            SearchResult(title=f"Movie {index}", url=f"magnet:?xt=urn:btih:{index:040d}", source="site_plugin:BT1207")
            for index in range(1, 6)
        ]

        markup = magnet_results_reply_markup({"title": "Movie"}, results)

        self.assertEqual(len(markup["inline_keyboard"]), 1)
        self.assertEqual([button["text"] for button in markup["inline_keyboard"][0]], ["1", "2", "3", "4", "5"])

    def test_magnet_reply_uses_size_from_result_context(self) -> None:
        result = SearchResult(
            title="The.Furious.2026.2160p",
            url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source="site_plugin:BT1207",
            context="文件大小：16.44 GB",
        )

        reply = magnet_results_reply({"title": "The Furious", "release_date": "2026-01-01"}, [result])

        self.assertIn("16.44 GB", reply)
        self.assertNotIn("未知", reply)

    def test_site_plugin_parse_carries_page_size_to_bot_result(self) -> None:
        adapter = RssTorznabAdapter()
        html = """
        <html><head><title>The Furious 2026</title></head><body>
          <h1>The Furious 2026 2160p</h1>
          <p>文件大小：6.59 GB 文件数量：9</p>
          <a href="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">download</a>
        </body></html>
        """

        results = adapter._parse_magnet_web_page({"name": "BT1207", "type": "site_plugin"}, "https://bt1207to.cc/detail/1.html", html)

        self.assertEqual(len(results), 1)
        self.assertEqual(_resource_size(results[0]), "6.59 GB")

    def test_bot_magnet_queries_include_no_year_and_original_title(self) -> None:
        queries = _fast_magnet_queries("新警察故事 2004", ["新警察故事", "New Police Story"])

        self.assertEqual(queries[:3], ["新警察故事 2004", "新警察故事", "New Police Story"])

    def test_bot_magnet_query_batches_retry_with_looser_query(self) -> None:
        batches = _fast_magnet_query_batches("钢铁侠 2008", ["Iron Man"])

        self.assertEqual(batches[0], ["钢铁侠 2008"])
        self.assertIn("钢铁侠", batches[1])

    def test_bot_magnet_alias_matching_accepts_original_title(self) -> None:
        subscription = {"title": "钢铁侠", "search_aliases": ["钢铁侠", "Iron Man"]}

        self.assertTrue(_bot_title_or_alias_matches(subscription, "ironman20081080p"))

    def test_bot_magnet_alias_matching_rejects_cjk_suffix_title(self) -> None:
        subscription = {"title": "蜘蛛侠", "search_aliases": ["蜘蛛侠", "Spider-Man"], "release_year": 2002}

        self.assertFalse(_bot_title_or_alias_matches(subscription, "暗影蜘蛛侠 2026 Spider-Noir"))

    def test_bot_magnet_alias_matching_accepts_cjk_title_before_year_bracket(self) -> None:
        subscription = {"title": "钢铁侠", "search_aliases": ["钢铁侠", "Iron Man"], "release_year": 2008}

        self.assertTrue(_bot_title_or_alias_matches(subscription, "钢铁侠 (2008 )"))

    def test_bot_magnet_ranking_accepts_exact_title_without_year(self) -> None:
        subscription = {"title": "钢铁侠", "search_aliases": ["钢铁侠", "Iron Man"], "release_year": 2008}
        results = [
            SearchResult(title="钢铁侠", url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site_plugin:BT1207"),
            SearchResult(title="钢铁侠与美国队长：英雄集结 2014", url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", source="site_plugin:QMP4"),
        ]

        ranked = _rank_magnet_results(subscription, results)

        self.assertEqual([item.title for item in ranked], ["钢铁侠"])

    def test_fast_source_options_limit_detail_fetches(self) -> None:
        source = _fast_source_options({"name": "BT1207", "type": "site_plugin", "plugin": "bt1207"})

        self.assertEqual(source["_fast_detail_limit"], 3)
        self.assertLess(source["_bt1207_detail_delay"], 0.6)
        self.assertLessEqual(source["_request_timeout"], 8.0)

    def test_bot_magnet_search_cache_roundtrip(self) -> None:
        _magnet_search_cache.clear()
        result = SearchResult(
            title="Drama 2026 1080p",
            url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source="site_plugin:test",
        )

        _store_magnet_search_cache("tv", 123, 5, {"name": "Drama", "media_type": "tv"}, [result])
        cached = _cached_magnet_search("tv", 123, 5)

        self.assertIsNotNone(cached)
        self.assertEqual(cached[0]["name"], "Drama")
        self.assertEqual(cached[1][0].url, result.url)


class TelegramBotMagnetSearchAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_magnets_for_tmdb_returns_cached_results_without_tmdb_call(self) -> None:
        _magnet_search_cache.clear()
        result = SearchResult(
            title="Drama 2026 1080p",
            url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source="site_plugin:test",
        )
        _store_magnet_search_cache("tv", 123, 5, {"name": "Drama", "media_type": "tv"}, [result])

        with patch("app.services.magnet.search.TmdbAdapter") as tmdb_cls:
            tmdb_cls.return_value.detail = AsyncMock(side_effect=AssertionError("tmdb should not be called"))
            detail, results = await search_magnets_for_tmdb("tv", 123, 5)

        self.assertEqual(detail["name"], "Drama")
        self.assertEqual([item.url for item in results], [result.url])

    async def test_single_source_error_does_not_fail_whole_magnet_search(self) -> None:
        class Adapter:
            async def _fetch_source_for_queries(self, source, queries):
                if source["name"] == "bad":
                    raise RuntimeError("source failed")
                return [SearchResult(title="ok", url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site_plugin:ok")]

        groups = await _fetch_priority_sources(Adapter(), [{"name": "bad"}, {"name": "ok"}], ["Drama"])

        self.assertEqual(groups[0], [])
        self.assertEqual(len(groups[1]), 1)

    async def test_priority_search_returns_before_slow_source_when_enough_matches(self) -> None:
        class Adapter:
            def _source_priority(self, source):
                return source.get("priority", 0)

            async def _fetch_source_for_queries(self, source, queries):
                if source["name"] == "slow":
                    await asyncio.sleep(2)
                    return [SearchResult(title="新警察故事 2004", url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", source="site_plugin:slow")]
                await asyncio.sleep(0.01)
                return [
                    SearchResult(title=f"新警察故事 2004 {index}", url=f"magnet:?xt=urn:btih:{index:040d}", source="site_plugin:fast")
                    for index in range(1, 6)
                ]

        subscription = {"title": "新警察故事", "release_year": 2004, "media_type": "movie"}
        started = time.perf_counter()
        results, searched, early = await _fetch_priority_sources_until_ranked(
            Adapter(),
            [{"name": "slow"}, {"name": "fast"}],
            ["新警察故事 2004"],
            subscription,
            5,
            [],
        )

        self.assertLess(time.perf_counter() - started, 1)
        self.assertTrue(early)
        self.assertEqual(searched, 1)
        self.assertEqual(len(results), 5)
