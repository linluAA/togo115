from __future__ import annotations

from app.db import add_log
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription_candidate_decision import decide_resource_candidate
from app.services.subscription_episode_parser import _episode_keys_from_text_for_subscription, _missing_episode_keys
from app.services.subscription_matching import _result_debug_payload
from app.services.subscription_result_utils import _result_text

SKIP_REASONS = {"episodes_already_in_library", "episodes_not_needed", "movie_already_in_library"}


def resource_allowed_for_subscription(
    subscription: dict | None,
    result: SearchResult,
    *,
    scope: str,
    reject_reasons: set[str] | None = None,
) -> bool:
    """Return whether a resource is still worth saving or delivering for a subscription."""
    if not subscription:
        return True
    try:
        decision = decide_resource_candidate(subscription, result)
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "资源缺集守卫判断异常，已跳过该资源",
            {"id": subscription.get("id"), **_result_debug_payload(result), "scope": scope, "error": str(exc)},
        )
        return False
    if decision.accepted:
        return True
    reason = decision.reason
    if reject_reasons is not None and reason not in reject_reasons:
        reason = _episode_skip_reason(subscription, result) or reason
    if reject_reasons is not None and reason not in reject_reasons:
        return True
    add_log(
        "debug" if reason in SKIP_REASONS else "warning",
        "subscription",
        "资源不在订阅缺失范围内，已跳过",
        {
            "id": subscription.get("id"),
            **_result_debug_payload(result),
            "scope": scope,
            "reason": reason,
            "episodes": [f"{season}x{episode}" for season, episode in sorted(decision.episodes)],
            "missing_coverage": [f"{season}x{episode}" for season, episode in sorted(decision.missing_coverage)],
        },
    )
    return False


def _episode_skip_reason(subscription: dict, result: SearchResult) -> str:
    if subscription.get("media_type") != "tv":
        return "movie_already_in_library" if subscription.get("in_library") else ""
    episodes = _episode_keys_from_text_for_subscription(subscription, _result_text(result))
    if not episodes:
        return ""
    missing = _missing_episode_keys(subscription)
    if missing and not episodes.intersection(missing):
        return "episodes_already_in_library"
    if not missing and _has_episode_scope(subscription):
        return "episodes_not_needed"
    return ""


def _has_episode_scope(subscription: dict) -> bool:
    return bool(
        subscription.get("tmdb_total_count")
        or subscription.get("tmdb_seasons")
        or subscription.get("emby_count")
        or subscription.get("emby_episode_keys")
        or subscription.get("emby_episodes")
        or subscription.get("in_library")
    )
