
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.link.downloads import is_valid_download_link
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.episode.parser import episode_keys_from_text_for_subscription, missing_episode_keys
from app.services.subscription.library.match import result_matches_missing_episodes
from app.services.subscription.match.matching import (
    normalize_quality_rules,
    _quality_rule_skip_reason,
    _result_is_site_plugin,
    result_priority,
    result_skip_reason,
    result_text,
    _text_contains_any,
    result_matches_subscription,
)


@dataclass(frozen=True)
class ResourceDecision:
    result: SearchResult
    accepted: bool
    reason: str
    score: int
    episodes: frozenset[tuple[int, int]]
    missing_episodes: frozenset[tuple[int, int]]
    missing_coverage: frozenset[tuple[int, int]]

    @property
    def coverage_count(self) -> int:
        return len(self.missing_coverage)


def decide_resource_candidate(subscription: dict, result: SearchResult, *extra_texts: str) -> ResourceDecision:
    """Return a single explainable decision for subscription resource matching."""
    episodes = frozenset(episode_keys_from_text_for_subscription(subscription, result_text(result, *extra_texts)))
    missing = frozenset(missing_episode_keys(subscription))
    coverage = frozenset(episodes & missing) if missing else frozenset()
    reason = _candidate_reject_reason(subscription, result, episodes, missing, coverage, *extra_texts)
    accepted = not reason
    return ResourceDecision(
        result=result,
        accepted=accepted,
        reason=reason or "matched",
        score=_candidate_score(subscription, result, episodes, coverage, accepted),
        episodes=episodes,
        missing_episodes=missing,
        missing_coverage=coverage,
    )


def _candidate_reject_reason(
    subscription: dict,
    result: SearchResult,
    episodes: frozenset[tuple[int, int]],
    missing: frozenset[tuple[int, int]],
    coverage: frozenset[tuple[int, int]],
    *extra_texts: str,
) -> str:
    if not is_valid_download_link(getattr(result, "url", "")):
        return "invalid_download_link"
    if not result_matches_subscription(subscription, result, *extra_texts):
        return result_skip_reason(subscription, result, *extra_texts) or "subscription_mismatch"
    if not result_matches_missing_episodes(subscription, result, *extra_texts):
        if subscription.get("media_type") == "tv" and episodes:
            return "episodes_already_in_library" if not coverage else "episodes_not_needed"
        if subscription.get("media_type") != "tv" and subscription.get("in_library"):
            return "movie_already_in_library"
        return result_skip_reason(subscription, result, *extra_texts) or "missing_episode_mismatch"
    return ""


def _candidate_score(
    subscription: dict,
    result: SearchResult,
    episodes: frozenset[tuple[int, int]],
    coverage: frozenset[tuple[int, int]],
    accepted: bool,
) -> int:
    if not accepted:
        return 0
    score = 100
    if subscription.get("media_type") == "tv":
        if coverage:
            score += min(len(coverage), 50) * 20
            if episodes and coverage == episodes:
                score += 30
            elif episodes:
                score += 10
        elif not episodes:
            score += 5
    score += _quality_preference_score(subscription, result) * 25
    score += min(max(result_priority(result), -50), 50)
    if _result_is_site_plugin(result):
        score += 5
    return score


def fallback_candidate_sort_key(subscription: dict | None, result: SearchResult) -> tuple[Any, ...]:
    decision = decide_resource_candidate(subscription, result) if subscription else None
    coverage_count = decision.coverage_count if decision else 0
    exact_missing = bool(decision and decision.episodes and decision.episodes == decision.missing_coverage)
    return (
        -coverage_count,
        0 if exact_missing else 1,
        -_quality_preference_score(subscription, result),
        -result_priority(result),
        0 if _result_is_site_plugin(result) else 1,
        len(str(getattr(result, "title", "") or "")),
        str(getattr(result, "message_id", "") or ""),
        str(getattr(result, "url", "") or ""),
    )


def _quality_preference_score(subscription: dict | None, result: SearchResult) -> int:
    if not subscription:
        return 0
    rules = normalize_quality_rules(subscription.get("quality_rules"))
    preferred_quality = rules.get("preferred_quality") or []
    if preferred_quality and _text_contains_any(result_text(result), preferred_quality):
        return 1
    if not _quality_rule_skip_reason(subscription, result):
        return 0
    return -1
