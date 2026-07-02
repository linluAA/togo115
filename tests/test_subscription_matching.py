import unittest

from app.services.integrations import SearchResult
from app.services.subscription import _canonical_115_url, _resource_dedupe_key, result_matches_missing_episodes, result_matches_subscription


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

    def test_release_year_rejects_other_versions_when_year_is_present(self) -> None:
        subscription = {"title": "生化危机战", "media_type": "movie", "tmdb_id": 0, "release_year": 2015, "keywords": ["生化危机战"]}

        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 (2015) 1080p")))
        self.assertFalse(result_matches_subscription(subscription, result("生化危机 Resident Evil (2022) 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("生化危机战 1080p\n发布时间：2026-07-01")))

    def test_title_year_is_used_as_year_constraint_not_title_text(self) -> None:
        subscription = {"title": "爱丽丝（2020）", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝.2020 - S01E01 1080p")))
        self.assertFalse(result_matches_subscription(subscription, result("爱丽丝与史蒂夫.2026 - S01E01 1080p")))

    def test_magnet_web_requires_year_evidence_when_subscription_has_year(self) -> None:
        subscription = {"title": "爱丽丝（2020）", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertFalse(result_matches_subscription(subscription, SearchResult(title="爱丽丝 - S01E01 1080p", url="magnet:?xt=urn:btih:aaa", source="magnet_web:站点", context="爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, SearchResult(title="爱丽丝 - S01E01 1080p", url="magnet:?xt=urn:btih:bbb", source="magnet_web:站点", context="爱丽丝（2020）\n爱丽丝 - S01E01 1080p")))
        self.assertTrue(result_matches_subscription(subscription, SearchResult(title="爱丽丝.2020.1080p.WEB-DL", url="magnet:?xt=urn:btih:ddd", source="magnet_web:站点", context="爱丽丝.2020.1080p.WEB-DL")))
        self.assertFalse(result_matches_subscription(subscription, SearchResult(title="爱丽丝与史蒂夫 (2026) 1080p", url="magnet:?xt=urn:btih:ccc", source="magnet_web:站点", context="爱丽丝（2020）\n爱丽丝与史蒂夫 (2026) 1080p")))

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


if __name__ == "__main__":
    unittest.main()
