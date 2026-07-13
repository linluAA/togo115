from __future__ import annotations

from app.db import add_log
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription_candidate_decision import decide_resource_candidate
from app.services.subscription_matching import _result_debug_payload


def _matching_results(subscription: dict, results: list[SearchResult], *extra_texts: str) -> list[SearchResult]:
    matched: list[SearchResult] = []
    for result in results:
        try:
            decision = decide_resource_candidate(subscription, result, *extra_texts)
            if decision.accepted:
                matched.append(result)
                continue
            add_log(
                "debug",
                "subscription",
                "资源候选未通过统一匹配决策，已跳过",
                {
                    "id": subscription.get("id"),
                    **_result_debug_payload(result),
                    "reason": decision.reason,
                    "score": decision.score,
                    "episodes": [f"{season}x{episode}" for season, episode in sorted(decision.episodes)],
                    "missing_coverage": [f"{season}x{episode}" for season, episode in sorted(decision.missing_coverage)],
                },
            )
        except Exception as exc:
            add_log(
                "warning",
                "subscription",
                "资源匹配判断异常，已跳过单条结果",
                {"id": subscription.get("id"), **_result_debug_payload(result), "error": str(exc)},
            )
    return matched


def _unmatched_results(results: list[SearchResult], matched: list[SearchResult]) -> list[SearchResult]:
    matched_ids = {id(result) for result in matched}
    return [result for result in results if id(result) not in matched_ids]
