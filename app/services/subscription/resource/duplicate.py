from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from typing import Any

from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.matching import (
    compact_match_text,
    episode_keys_from_text_for_subscription,
    result_text,
    title_without_year,
)
from app.services.subscription.resource.resources import (
    existing_resource_rows as existing_resource_rows,
    resource_dedupe_key as _resource_dedupe_key,
    resource_status_is_effective as _resource_status_is_effective,
)


def resource_already_exists(
    conn: sqlite3.Connection,
    subscription_id: int,
    result: SearchResult,
    subscription: dict | None = None,
    existing_rows: list[dict[str, Any]] | None = None,
) -> str | None:
    candidate_key = _resource_dedupe_key(result.url)
    result_episodes = episode_keys_from_text_for_subscription(subscription, result_text(result))
    result_title_key = compact_match_text(title_without_year(getattr(result, "title", "")) or getattr(result, "title", ""))
    rows = existing_rows if existing_rows is not None else existing_resource_rows(conn, subscription_id)
    for row in rows:
        reason = _duplicate_reason_for_row(subscription, result_episodes, result_title_key, candidate_key, row)
        if reason:
            return reason
    return None


def _duplicate_reason_for_row(
    subscription: dict | None,
    result_episodes: set[tuple[int, int]],
    result_title_key: str,
    candidate_key: tuple[str, str] | None,
    row: dict[str, Any],
) -> str | None:
    existing_url = row.get("url") or ""
    existing_effective = _resource_status_is_effective(row.get("status"))
    if candidate_key and _resource_dedupe_key(existing_url) == candidate_key:
        return f"same_{candidate_key[0]}" if existing_effective else None
    if not existing_effective:
        return None
    existing_episodes = episode_keys_from_text_for_subscription(subscription, str(row.get("title") or ""))
    if result_episodes and existing_episodes and result_episodes.issubset(existing_episodes):
        return "covered_episodes"
    return _similar_title_reason(result_title_key, row, result_episodes, existing_episodes)


def _similar_title_reason(
    result_title_key: str,
    row: dict[str, Any],
    result_episodes: set[tuple[int, int]],
    existing_episodes: set[tuple[int, int]],
) -> str | None:
    """Treat similar titles as duplicates only when episode scope is comparable.

    Bare titles (no episode keys) must not block a newer pack that carries an
    explicit range such as S01E01-E21. Otherwise progressive TG hits with a
    clean drama title permanently suppress later packs that cover missing eps.
    """
    existing_title_key = compact_match_text(title_without_year(row.get("title")) or row.get("title"))
    if not result_title_key or not existing_title_key:
        return None
    similarity = SequenceMatcher(None, result_title_key, existing_title_key).ratio()
    if similarity < 0.94:
        return None
    if result_episodes or existing_episodes:
        if result_episodes != existing_episodes:
            return None
    return "similar_title"
