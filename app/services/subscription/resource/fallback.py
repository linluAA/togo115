from __future__ import annotations

import sqlite3
from typing import Any

from app.db import add_log, row_to_dict
from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link_downloads import is_115_share_link
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.candidate_decision import fallback_candidate_sort_key
from app.services.subscription.match.matching import (
    _episode_keys_from_text_for_subscription,
    _result_debug_payload,
    _result_is_fallback_source,
    _result_text,
    _subscription_match_text,
    _subscription_required_terms,
    _title_term_in_text,
    _tmdb_ids_from_text,
)


def _subscription_115_resources(conn: sqlite3.Connection, subscription_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT title, url, status FROM resources WHERE subscription_id = ? AND status NOT IN ('failed', 'pending_recheck', 'skipped') ORDER BY id DESC",
        (subscription_id,),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows if PAN115_URL_RE.match(row["url"] or "")]


def _fallback_blocked_by_primary_resource(
    conn: sqlite3.Connection,
    subscription: dict,
    result: SearchResult,
    existing_115: list[dict[str, Any]] | None = None,
) -> bool:
    if not _result_is_fallback_source(result):
        return False
    if existing_115 is None:
        existing_115 = _subscription_115_resources(conn, int(subscription["id"]))
    if not existing_115:
        return False
    if not is_115_share_link(getattr(result, "url", "")):
        return False
    if subscription.get("media_type") != "tv":
        return True

    result_episodes = _episode_keys_from_text_for_subscription(subscription, _result_text(result))
    if not result_episodes:
        return True
    for item in existing_115:
        existing_episodes = _episode_keys_from_text_for_subscription(subscription, str(item.get("title") or ""))
        if not existing_episodes or result_episodes.issubset(existing_episodes):
            return True
    return False


def _results_may_match_subscription(subscription: dict, results: list[SearchResult], *extra_texts: str) -> bool:
    title_term, _ = _subscription_required_terms(subscription)
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "").lstrip("0")
    if not title_term and not subscription_tmdb_id:
        return True
    for result in results:
        if _result_may_match_subscription(subscription, result, title_term, subscription_tmdb_id, *extra_texts):
            return True
    return False


def _result_may_match_subscription(
    subscription: dict,
    result: SearchResult,
    title_term: str,
    subscription_tmdb_id: str,
    *extra_texts: str,
) -> bool:
    try:
        text = _subscription_match_text(result, *extra_texts)
        if subscription_tmdb_id and subscription_tmdb_id in _tmdb_ids_from_text(text):
            return True
        return bool(title_term and _title_term_in_text(title_term, text))
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "实时资源预匹配异常，已跳过单条结果",
            {"id": subscription.get("id"), **_result_debug_payload(result), "error": str(exc)},
        )
        return False


def _fallback_result_candidates(results: list[SearchResult], subscription: dict | None = None) -> list[SearchResult]:
    return sorted(results, key=lambda result: fallback_candidate_sort_key(subscription, result))


def _best_fallback_result(results: list[SearchResult], subscription: dict | None = None) -> SearchResult | None:
    candidates = _fallback_result_candidates(results, subscription)
    return candidates[0] if candidates else None
