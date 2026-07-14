from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.candidate_decision import decide_resource_candidate
from app.services.subscription.match.matching import _result_debug_payload
from app.services.subscription.resource.ops import _fallback_blocked_by_primary_resource


def _result_matches_subscription(subscription: dict, result: SearchResult) -> bool:
    try:
        decision = decide_resource_candidate(subscription, result)
        if decision.accepted:
            return True
        if decision.reason in {"episodes_already_in_library", "episodes_not_needed", "movie_already_in_library"}:
            add_log(
                "debug",
                "subscription",
                "\u5b9e\u65f6\u8d44\u6e90\u4e0d\u5728\u7f3a\u96c6\u8303\u56f4\uff0c\u5df2\u8df3\u8fc7",
                {
                    "id": subscription["id"],
                    "title": str(getattr(result, "title", "") or "")[:120],
                    "reason": decision.reason,
                    "episodes": [f"{season}x{episode}" for season, episode in sorted(decision.episodes)],
                    "missing_coverage": [f"{season}x{episode}" for season, episode in sorted(decision.missing_coverage)],
                },
            )
        else:
            add_log(
                "debug",
                "subscription",
                "\u5b9e\u65f6\u8d44\u6e90\u672a\u901a\u8fc7\u7edf\u4e00\u5339\u914d\u51b3\u7b56\uff0c\u5df2\u8df3\u8fc7",
                {
                    "id": subscription["id"],
                    **_result_debug_payload(result),
                    "reason": decision.reason,
                    "score": decision.score,
                },
            )
        return False
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "\u5b9e\u65f6\u8d44\u6e90\u5339\u914d\u5224\u65ad\u5f02\u5e38\uff0c\u5df2\u8df3\u8fc7\u5355\u6761\u7ed3\u679c",
            {"id": subscription["id"], **_result_debug_payload(result), "error": str(exc)},
        )
        return False


def _fallback_is_blocked(conn, subscription: dict, result: SearchResult, existing_115: list[dict[str, Any]]) -> bool:
    try:
        blocked = _fallback_blocked_by_primary_resource(conn, subscription, result, existing_115)
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "订阅源/磁力阻断判断异常，已跳过单条结果",
            {"id": subscription["id"], **_result_debug_payload(result), "error": str(exc)},
        )
        return True
    if blocked:
        add_log(
            "debug",
            "subscription",
            "订阅已有 115 资源，跳过订阅源/磁力结果",
            {"id": subscription["id"], "title": str(getattr(result, "title", "") or "")[:120]},
        )
    return blocked
