import unittest
import sqlite3

from app.services.integrations import SearchResult
from app.services.subscription.resource.resources import canonical_115_url as _canonical_115_url, resource_dedupe_key as _resource_dedupe_key
from app.services.subscription.resource.ops import fallback_blocked_by_primary_resource, resource_already_exists
from app.services.subscription.library.match import result_matches_missing_episodes
from app.services.subscription.match.matching import result_matches_subscription
from app.services.subscription.resource.matching import matching_results
from app.services.subscription.episode.parser import episodes_from_text


def result(text: str) -> SearchResult:
    return SearchResult(title=text[:120], url="https://115cdn.com/s/example?password=abcd", source="test", context=text)


class SubscriptionMatchingTest(unittest.TestCase):
    def test_115cdn_and_115_links_share_same_dedupe_key(self) -> None:
        first = "https://115cdn.com/s/swssxf43nbi?password=8888"
        second = "https://115.com/s/swssxf43nbi?password=8888"

        self.assertEqual(_canonical_115_url(first), second)
        self.assertEqual(_resource_dedupe_key(first), _resource_dedupe_key(second))

    def test_title_boundary_rejects_longer_chinese_title(self) -> None:
        subscription = {"title": "爱丽丝", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("名称: 爱丽丝.2020 - S01E02")))
        self.assertFalse(result_matches_subscription(subscription, result("名称: 爱丽丝与史蒂夫.2026 - S01E02")))

    def test_tmdb_id_takes_precedence_over_partial_title(self) -> None:
        subscription = {"title": "爱丽丝", "media_type": "tv", "tmdb_id": 12345, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝.2020 {tmdb-12345} - S01E01")))
        self.assertTrue(result_matches_subscription(subscription, result("电视剧：别名\nTMDB ID: 12345\nS01E01")))
        self.assertFalse(result_matches_subscription(subscription, result("爱丽丝与史蒂夫.2026 {tmdb-318203} - S01E02")))

    def test_media_type_label_is_valid_chinese_title_prefix(self) -> None:
        subscription = {"title": "爱情有烟火", "media_type": "tv", "tmdb_id": 230311, "release_year": 2026, "keywords": ["爱情有烟火"]}

        self.assertTrue(result_matches_subscription(subscription, result("电视剧：爱情有烟火 (2026)\nS01E01-E36\nTMDB ID: 230311")))

    def test_screenshot_style_tg_caption_matches_subscription_and_missing_episodes(self) -> None:
        subscription = {
            "title": "大主宰",
            "media_type": "tv",
            "tmdb_id": 226045,
            "release_year": 2023,
            "keywords": ["大主宰"],
            "tmdb_total_count": 80,
            "emby_episode_keys": [],
        }
        caption = "\n".join(
            [
                "电视剧： 大主宰 (2023)",
                "S01E01-E80",
                "TMDB ID: 226045",
                "质量: [4K] [HDR10]",
                "链接: https://115.com/s",
                "/swslzrw3nbi?password=8888",
            ]
        )
        link_result = result(caption)

        self.assertTrue(result_matches_subscription(subscription, link_result))
        self.assertTrue(result_matches_missing_episodes(subscription, link_result))

    def test_tg_caption_update_to_episode_ignores_115_url_numbers(self) -> None:
        subscription = {
            "title": "灿如繁星",
            "media_type": "tv",
            "tmdb_id": 285143,
            "release_year": 2026,
            "keywords": ["灿如繁星"],
            "tmdb_total_count": 8,
            "emby_episode_keys": [],
        }
        caption = "\n".join(
            [
                "📺 电视剧： **灿如繁星 (2026) 更新至8集 4K DV**",
                "⭐ 评分：7.0",
                "🍿 TMDB ID：285143",
                "💾 大小：22.13GB",
                "📼 质量：4K / DV / WEB-DL / H.265",
                "🔗 链接：https://115cdn.com/s/swsslep63nbi?password=8888",
            ]
        )
        link_result = result(caption)

        self.assertNotIn((1, 63), episodes_from_text(caption))
        self.assertTrue(result_matches_subscription(subscription, link_result))
        self.assertTrue(result_matches_missing_episodes(subscription, link_result))

    def test_update_to_episode_pack_matches_missing_middle_episode(self) -> None:
        subscription = {
            "title": "灿如繁星",
            "media_type": "tv",
            "keywords": ["灿如繁星"],
            "tmdb_total_count": 8,
            "emby_episode_keys": ["1x1", "1x2", "1x4", "1x5", "1x6", "1x7", "1x8"],
        }

        self.assertTrue(result_matches_missing_episodes(subscription, result("灿如繁星 更新至8集 4K")))

    def test_release_year_rejects_other_versions_when_year_is_present(self) -> None:
        subscription = {"title": "生化危机战", "media_type": "movie", "tmdb_id": 0, "release_year": 2015, "keywords": ["生化危机战"]}

        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 (2015) 1080p")))
        self.assertFalse(result_matches_subscription(subscription, result("生化危机 Resident Evil (2022) 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 1080p\n发布时间：2026-07-01")))
        self.assertTrue(result_matches_subscription(subscription, result("[2016.01.02] 生化危机战 [2015年动作] 1080p")))

    def test_title_year_is_used_as_year_constraint_not_title_text(self) -> None:
        subscription = {"title": "爱丽丝（2020）", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝.2020 - S01E01 1080p")))
        self.assertFalse(result_matches_subscription(subscription, result("爱丽丝与史蒂夫.2026 - S01E01 1080p")))

    def test_magnet_web_allows_missing_year_but_rejects_conflicting_year(self) -> None:
        subscription = {"title": "爱丽丝（2020）", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, SearchResult(title="爱丽丝 - S01E01 1080p", url="magnet:?xt=urn:btih:aaa", source="magnet_web:站点", context="爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, SearchResult(title="爱丽丝 - S01E01 1080p", url="magnet:?xt=urn:btih:bbb", source="magnet_web:站点", context="爱丽丝（2020）\n爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, SearchResult(title="爱丽丝.2020.1080p.WEB-DL", url="magnet:?xt=urn:btih:ddd", source="magnet_web:站点", context="爱丽丝.2020.1080p.WEB-DL")))
        self.assertFalse(result_matches_subscription(subscription, SearchResult(title="爱丽丝与史蒂夫 (2026) 1080p", url="magnet:?xt=urn:btih:ccc", source="magnet_web:站点", context="爱丽丝（2020）\n爱丽丝与史蒂夫 (2026) 1080p")))

    def test_release_year_context_does_not_mask_wrong_title_year(self) -> None:
        subscription = {"title": "Alice (2020)", "media_type": "tv", "tmdb_id": 0, "keywords": ["Alice"]}

        self.assertFalse(
            result_matches_subscription(
                subscription,
                SearchResult(
                    title="Alice and Steve (2026) 1080p",
                    url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    source="magnet_web:test",
                    context="Alice (2020)\nAlice and Steve (2026) 1080p",
                ),
            )
        )
        self.assertFalse(
            result_matches_subscription(
                subscription,
                SearchResult(
                    title="Thin Ice (2026) 1080p",
                    url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    source="magnet_web:test",
                    context="Alice (2020)\nThin Ice (2026) 1080p",
                ),
            )
        )
        self.assertTrue(
            result_matches_subscription(
                {"title": "Robot Movie", "media_type": "movie", "tmdb_id": 0, "release_year": 2010, "keywords": ["Robot Movie"]},
                result("[2011.03.22] Robot Movie [2010 India Action] 1080p"),
            )
        )

    def test_magnet_dedupe_uses_btih_hash(self) -> None:
        first = "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&dn=first"
        second = "magnet:?dn=second&xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        self.assertEqual(_resource_dedupe_key(first), _resource_dedupe_key(second))

    def test_missing_episode_filter_uses_link_context_only(self) -> None:
        subscription = {
            "title": "爱丽丝",
            "media_type": "tv",
            "keywords": ["爱丽丝"],
            "tmdb_total_count": 16,
            "emby_episode_keys": ["1x1", "1x2"],
        }

        link_result = result("名称: 爱丽丝.2020 - 第 3 集")
        unrelated_message = "名称: 爱丽丝与史蒂夫.2026 - 第 2 集\n名称: 如履薄冰 (2026)"

        self.assertTrue(result_matches_subscription(subscription, link_result, unrelated_message))
        self.assertTrue(result_matches_missing_episodes(subscription, link_result, unrelated_message))

    def test_missing_episode_filter_rejects_owned_episode(self) -> None:
        subscription = {
            "title": "爱丽丝",
            "media_type": "tv",
            "keywords": ["爱丽丝"],
            "tmdb_total_count": 16,
            "emby_episode_keys": ["1x1", "1x2"],
        }

        link_result = result("名称: 爱丽丝.2020 - 第 2 集")

        self.assertFalse(result_matches_missing_episodes(subscription, link_result))

    def test_full_season_pack_matches_when_it_contains_missing_episodes(self) -> None:
        subscription = {
            "title": "爱情有烟火",
            "media_type": "tv",
            "keywords": ["爱情有烟火"],
            "tmdb_id": 230311,
            "release_year": 2026,
            "tmdb_total_count": 36,
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 33)],
        }
        link_result = result(
            "电视剧：爱情有烟火 (2026)\n"
            "S01E01-E36\n"
            "TMDB ID: 230311\n"
            "链接：https://115.com/s/swssxf43nbi?password=8888"
        )

        self.assertTrue(result_matches_subscription(subscription, link_result))
        self.assertTrue(result_matches_missing_episodes(subscription, link_result))

    def test_multi_season_pack_names_match_missing_season(self) -> None:
        subscription = {
            "title": "星际档案",
            "media_type": "tv",
            "keywords": ["星际档案"],
            "tmdb_seasons": [
                {"season_number": 1, "episode_count": 10},
                {"season_number": 2, "episode_count": 12},
            ],
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 11)] + [f"2x{episode}" for episode in range(1, 7)],
        }

        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 S02 Complete 1080p")))
        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 第二季全集 1080p")))
        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 第二季第七集 1080p")))
        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 第2季 全12集 1080p")))
        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 S02 01-12 1080p")))
        self.assertFalse(result_matches_missing_episodes(subscription, result("星际档案 第1季全集 1080p")))
        self.assertFalse(result_matches_missing_episodes(subscription, result("星际档案 第01-12集全集 1080p")))
        self.assertFalse(result_matches_missing_episodes(subscription, result("星际档案 S02E03 Complete 1080p")))

    def test_full_episode_count_pack_can_infer_single_missing_season(self) -> None:
        subscription = {
            "title": "星际档案",
            "media_type": "tv",
            "keywords": ["星际档案"],
            "tmdb_seasons": [
                {"season_number": 1, "episode_count": 10},
                {"season_number": 2, "episode_count": 12},
            ],
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 11)],
        }

        self.assertTrue(result_matches_missing_episodes(subscription, result("星际档案 全12集 1080p")))

    def test_season_context_prevents_plain_range_from_defaulting_to_season_one(self) -> None:
        subscription = {
            "title": "星际档案",
            "media_type": "tv",
            "keywords": ["星际档案"],
            "tmdb_seasons": [
                {"season_number": 1, "episode_count": 10},
                {"season_number": 2, "episode_count": 12},
            ],
            "emby_episode_keys": [f"2x{episode}" for episode in range(1, 13)],
        }

        self.assertFalse(result_matches_missing_episodes(subscription, result("星际档案 S02 01-12 1080p")))

    def test_missing_episode_filter_uses_emby_count_when_episode_keys_are_absent(self) -> None:
        subscription = {
            "title": "南部档案",
            "media_type": "tv",
            "keywords": ["南部档案"],
            "tmdb_total_count": 30,
            "emby_count": 20,
            "emby_episode_keys": [],
        }

        owned_result = result("南部档案 - 第 20 集 1080p")
        missing_result = result("南部档案 - 第 21 集 1080p")
        pack_result = result("南部档案 - 第 01-30 集 1080p")

        self.assertFalse(result_matches_missing_episodes(subscription, owned_result))
        self.assertTrue(result_matches_missing_episodes(subscription, missing_result))
        self.assertTrue(result_matches_missing_episodes(subscription, pack_result))

    def test_primary_telegram_115_link_without_episode_text_is_allowed_for_missing_tv(self) -> None:
        subscription = {
            "title": "Drama",
            "media_type": "tv",
            "keywords": ["Drama"],
            "tmdb_total_count": 10,
            "emby_episode_keys": ["1x1", "1x2", "1x3", "1x4", "1x5"],
        }
        tg_result = SearchResult(
            title="Drama 1080p",
            url="https://115.com/s/dramacode?password=8888",
            source="-100123",
            context="Drama 1080p\nhttps://115.com/s/dramacode?password=8888",
        )
        fallback_result = SearchResult(
            title="Drama 1080p",
            url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source="site_plugin:test",
            context="Drama 1080p",
        )

        self.assertTrue(result_matches_subscription(subscription, tg_result))
        self.assertTrue(result_matches_missing_episodes(subscription, tg_result))
        self.assertFalse(result_matches_missing_episodes(subscription, fallback_result))

    def test_quality_rules_reject_excluded_words_and_pack_mode(self) -> None:
        subscription = {
            "title": "南部档案",
            "media_type": "tv",
            "keywords": ["南部档案"],
            "quality_rules": {"exclude_keywords": ["TC"], "accept_mode": "single"},
        }

        self.assertFalse(result_matches_subscription(subscription, result("南部档案 第 1 集 TC 1080p")))
        self.assertFalse(result_matches_subscription(subscription, result("南部档案 第 1-30 集 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("南部档案 第 21 集 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("南部档案 S02E03 Complete 1080p")))

    def test_dedupe_allows_pack_when_existing_resource_only_covers_part_of_missing_range(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)")
        try:
            conn.execute("INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '南部档案 第 01-20 集', 'https://115.com/s/old?password=aaaa', 'delivered')")
            self.assertIsNone(resource_already_exists(conn, 1, result("南部档案 第 01-30 集")))
        finally:
            conn.close()

    def test_failed_resource_does_not_cover_later_candidates(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)")
        subscription = {
            "title": "南部档案",
            "media_type": "tv",
            "keywords": ["南部档案"],
            "tmdb_total_count": 30,
            "emby_count": 20,
            "emby_episode_keys": [],
        }
        try:
            conn.execute("INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '南部档案 第 01-30 集', 'https://115.com/s/failed?password=aaaa', 'failed')")
            self.assertIsNone(resource_already_exists(conn, 1, result("南部档案 第 21 集"), subscription))
            self.assertIsNone(resource_already_exists(conn, 1, SearchResult(title="南部档案 第 21 集", url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site_plugin:test"), subscription))
        finally:
            conn.close()

    def test_invalid_download_url_is_not_a_matched_resource(self) -> None:
        subscription = {
            "id": 1,
            "title": "灿如繁星",
            "media_type": "tv",
            "tmdb_id": 285143,
            "release_year": 2026,
            "keywords": ["灿如繁星"],
            "tmdb_total_count": 8,
            "emby_episode_keys": [],
        }
        invalid = SearchResult(
            title="灿如繁星 (2026) S01E01-E08",
            url="https://115.com/s/",
            source="site_plugin:BT1207",
            context="灿如繁星 (2026) S01E01-E08\nTMDB ID: 285143",
        )

        self.assertEqual(matching_results(subscription, [invalid]), [])

    def test_failed_same_url_can_be_retried(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)")
        subscription = {
            "title": "灿如繁星",
            "media_type": "tv",
            "keywords": ["灿如繁星"],
            "tmdb_total_count": 8,
            "emby_episode_keys": [],
        }
        candidate = result("灿如繁星 S01E01-E08")
        try:
            conn.execute(
                "INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '灿如繁星 S01E01-E08', ?, 'failed')",
                (candidate.url,),
            )
            self.assertIsNone(resource_already_exists(conn, 1, candidate, subscription))
        finally:
            conn.close()

    def test_failed_115_resource_does_not_block_fallback_source(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)")
        subscription = {
            "id": 1,
            "title": "南部档案",
            "media_type": "tv",
            "keywords": ["南部档案"],
            "tmdb_total_count": 30,
            "emby_count": 20,
            "emby_episode_keys": [],
        }
        fallback = SearchResult(title="南部档案 第 21 集", url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", source="site_plugin:test")
        try:
            conn.execute("INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '南部档案 第 21 集', 'https://115.com/s/failed?password=aaaa', 'failed')")
            self.assertFalse(fallback_blocked_by_primary_resource(conn, subscription, fallback))
            conn.execute("INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '南部档案 第 21 集', 'https://115.com/s/delivered?password=aaaa', 'delivered')")
            self.assertFalse(fallback_blocked_by_primary_resource(conn, subscription, fallback))
            fallback_115 = SearchResult(title="南部档案 第 21 集", url="https://115.com/s/new115?password=bbbb", source="rss:test")
            self.assertTrue(fallback_blocked_by_primary_resource(conn, subscription, fallback_115))
        finally:
            conn.close()

    def test_magnet_fallback_not_blocked_by_existing_115_resource(self) -> None:
        from app.services.subscription.resource.fallback import fallback_blocked_by_primary_resource

        subscription = {"id": 1, "title": "后室", "media_type": "movie"}
        result = SearchResult(
            title="后室.mkv",
            url="magnet:?xt=urn:btih:547B057CDB063D40A2DDC75928ED4FB85163B15",
            source="site_plugin:BT1207",
        )

        blocked = fallback_blocked_by_primary_resource(None, subscription, result, [{"title": "后室", "url": "https://115.com/s/abc", "status": "pending"}])

        self.assertFalse(blocked)



    def test_similar_bare_title_does_not_block_pack_with_more_episodes(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)"
        )
        subscription = {
            "title": "野狗骨头",
            "media_type": "tv",
            "keywords": ["野狗骨头"],
            "tmdb_total_count": 32,
            "emby_count": 19,
            "emby_episode_keys": [f"1x{i}" for i in range(1, 20)],
        }
        try:
            conn.execute(
                "INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '野狗骨头', 'https://115.com/s/oldpack?password=aaaa', 'delivered')"
            )
            pack = SearchResult(
                title="野狗骨头(2026) S01E01-E21",
                url="https://115.com/s/newpack?password=bbbb",
                source="-1003793333793",
                context="剧集：野狗骨头(2026)\n季集：S01E01-E21\nTMDB ID：291392",
            )
            self.assertIsNone(resource_already_exists(conn, 1, pack, subscription))
        finally:
            conn.close()

    def test_covered_episodes_still_blocks_subset_pack(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE resources (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_id INTEGER, title TEXT, url TEXT, status TEXT)"
        )
        subscription = {
            "title": "野狗骨头",
            "media_type": "tv",
            "keywords": ["野狗骨头"],
            "tmdb_total_count": 32,
            "emby_count": 19,
            "emby_episode_keys": [f"1x{i}" for i in range(1, 20)],
        }
        try:
            conn.execute(
                "INSERT INTO resources (subscription_id, title, url, status) VALUES (1, '野狗骨头 S01E01-E21', 'https://115.com/s/big?password=aaaa', 'delivered')"
            )
            smaller = SearchResult(
                title="野狗骨头 S01E01-E19",
                url="https://115.com/s/small?password=bbbb",
                source="tg",
                context="野狗骨头 S01E01-E19",
            )
            self.assertEqual(resource_already_exists(conn, 1, smaller, subscription), "covered_episodes")
        finally:
            conn.close()


    def test_traditional_title_and_new_prefix_alias_match_subscription(self) -> None:
        subscription = {
            "title": "新攻壳机动队",
            "media_type": "tv",
            "tmdb_id": 255358,
            "keywords": ["新攻壳机动队"],
            "tmdb_total_count": 10,
            "emby_episode_keys": [],
        }
        card = result(
            "\n".join(
                [
                    "剧集：攻殻機動隊(2026)",
                    "TMDB ID：255358",
                    "季集：S01E01-E02",
                    "质量：1080P / WEB-DL / AVC",
                ]
            )
        )
        self.assertTrue(result_matches_subscription(subscription, card))
        self.assertTrue(result_matches_missing_episodes(subscription, card))

    def test_traditional_title_matches_without_tmdb_via_prefix_alias(self) -> None:
        subscription = {
            "title": "新攻壳机动队",
            "media_type": "tv",
            "keywords": ["新攻壳机动队"],
            "tmdb_total_count": 10,
            "emby_episode_keys": [],
        }
        card = result("剧集：攻殻機動隊(2026)\n季集：S01E01-E02")
        self.assertTrue(result_matches_subscription(subscription, card))
if __name__ == "__main__":
    unittest.main()

