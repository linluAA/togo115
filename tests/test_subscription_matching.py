import unittest

from app.services.integrations import SearchResult
from app.services.subscription import result_matches_missing_episodes, result_matches_subscription


def result(text: str) -> SearchResult:
    return SearchResult(title=text[:120], url="https://115cdn.com/s/example?password=abcd", source="test", context=text)


class SubscriptionMatchingTest(unittest.TestCase):
    def test_title_boundary_rejects_longer_chinese_title(self) -> None:
        subscription = {"title": "爱丽丝", "media_type": "tv", "tmdb_id": 0, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("名称: 爱丽丝.2020 - S01E02")))
        self.assertFalse(result_matches_subscription(subscription, result("名称: 爱丽丝与史蒂夫.2026 - S01E02")))

    def test_tmdb_id_takes_precedence_over_partial_title(self) -> None:
        subscription = {"title": "爱丽丝", "media_type": "tv", "tmdb_id": 12345, "keywords": ["爱丽丝"]}

        self.assertTrue(result_matches_subscription(subscription, result("爱丽丝.2020 {tmdb-12345} - S01E01")))
        self.assertFalse(result_matches_subscription(subscription, result("爱丽丝与史蒂夫.2026 {tmdb-318203} - S01E02")))

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


if __name__ == "__main__":
    unittest.main()
