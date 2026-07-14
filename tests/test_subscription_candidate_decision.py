
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.candidate_decision import decide_resource_candidate
from app.services.subscription.resource.fallback import fallback_result_candidates


def magnet(title: str, url_hash: str, priority: int = 0) -> SearchResult:
    return SearchResult(
        title=title,
        url="magnet:?xt=urn:btih:" + url_hash * 40,
        source="site_plugin:BT1207",
        context=title,
        priority=priority,
    )


def subscription() -> dict:
    return {
        "id": 29,
        "title": "\u91ce\u72d7\u9aa8\u5934",
        "media_type": "tv",
        "tmdb_total_count": 32,
        "emby_count": 8,
        "emby_episode_keys": [f"1x{episode}" for episode in range(1, 9)],
        "keywords": ["\u91ce\u72d7\u9aa8\u5934"],
    }


def test_decision_rejects_candidate_fully_covered_by_emby_library() -> None:
    result = magnet("\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f306\u96c6", "a")

    decision = decide_resource_candidate(subscription(), result)

    assert not decision.accepted
    assert decision.reason == "episodes_already_in_library"
    assert decision.episodes == frozenset((1, episode) for episode in range(1, 7))
    assert decision.missing_coverage == frozenset()


def test_decision_accepts_candidate_covering_missing_episodes() -> None:
    result = magnet("\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f312\u96c6", "b")

    decision = decide_resource_candidate(subscription(), result)

    assert decision.accepted
    assert decision.missing_coverage == frozenset((1, episode) for episode in range(9, 13))
    assert decision.score > 100


def test_fallback_candidates_prefer_missing_episode_coverage_over_source_priority() -> None:
    low_priority_but_useful = magnet("\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f312\u96c6", "c", priority=1)
    high_priority_but_owned = magnet("\u91ce\u72d7\u9aa8\u5934\uff082026\uff09\u66f4\u65b0\u81f306\u96c6", "d", priority=50)
    exact_missing = magnet("\u91ce\u72d7\u9aa8\u5934 S01E09-E10 1080p", "e", priority=5)

    candidates = fallback_result_candidates([high_priority_but_owned, low_priority_but_useful, exact_missing], subscription())

    assert candidates[0] is low_priority_but_useful
    assert candidates[-1] is high_priority_but_owned
