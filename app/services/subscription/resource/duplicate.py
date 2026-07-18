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
    index = _memo_resource_row_index(rows, subscription)

    if candidate_key and candidate_key in index["by_key"]:
        return f"same_{candidate_key[0]}"

    if result_episodes:
        for existing_episodes in index["episode_sets"]:
            if result_episodes.issubset(existing_episodes):
                return "covered_episodes"

    if result_title_key:
        for title_key, existing_episodes in index["title_entries"]:
            reason = _similar_title_against_key(result_title_key, title_key, result_episodes, existing_episodes)
            if reason:
                return reason
    return None


_ROW_INDEX_MEMO: dict[int, tuple[tuple[Any, ...], dict[str, Any]]] = {}
_ROW_INDEX_MEMO_MAX = 64


def _rows_memo_token(rows: list[dict[str, Any]], subscription: dict | None) -> tuple[Any, ...]:
    """Identity token that invalidates when the list content is prepended/replaced."""
    sub_token = id(subscription) if subscription is not None else 0
    if not rows:
        return (id(rows), sub_token, 0, 0, 0)
    first = rows[0]
    last = rows[-1]
    return (
        id(rows),
        sub_token,
        len(rows),
        id(first),
        id(last),
        str(first.get("url") or ""),
        str(last.get("url") or ""),
    )


def _memo_resource_row_index(rows: list[dict[str, Any]], subscription: dict | None) -> dict[str, Any]:
    """Reuse a per-list index while attach/save scans many candidates."""
    token = _rows_memo_token(rows, subscription)
    key = id(rows)
    cached = _ROW_INDEX_MEMO.get(key)
    if cached and cached[0] == token:
        return cached[1]
    index = _build_resource_row_index(rows, subscription)
    if len(_ROW_INDEX_MEMO) >= _ROW_INDEX_MEMO_MAX:
        # Drop an arbitrary oldest-ish entry; this cache is process-local and short-lived.
        _ROW_INDEX_MEMO.pop(next(iter(_ROW_INDEX_MEMO)), None)
    _ROW_INDEX_MEMO[key] = (token, index)
    return index


def _build_resource_row_index(rows: list[dict[str, Any]], subscription: dict | None) -> dict[str, Any]:
    """Build once-per-scan indexes so duplicate checks stay near O(1)/O(k)."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    episode_sets: list[set[tuple[int, int]]] = []
    title_entries: list[tuple[str, set[tuple[int, int]]]] = []
    for row in rows:
        if not _resource_status_is_effective(row.get("status")):
            continue
        key = _resource_dedupe_key(row.get("url") or "")
        if key and key not in by_key:
            by_key[key] = row
        existing_episodes = episode_keys_from_text_for_subscription(subscription, str(row.get("title") or ""))
        if existing_episodes:
            episode_sets.append(existing_episodes)
        title_key = compact_match_text(title_without_year(row.get("title")) or row.get("title"))
        if title_key:
            title_entries.append((title_key, existing_episodes))
    return {
        "by_key": by_key,
        "episode_sets": episode_sets,
        "title_entries": title_entries,
    }


def _similar_title_against_key(
    result_title_key: str,
    existing_title_key: str,
    result_episodes: set[tuple[int, int]],
    existing_episodes: set[tuple[int, int]],
) -> str | None:
    if not result_title_key or not existing_title_key:
        return None
    similarity = SequenceMatcher(None, result_title_key, existing_title_key).ratio()
    if similarity < 0.94:
        return None
    if result_episodes or existing_episodes:
        if result_episodes != existing_episodes:
            return None
    return "similar_title"


def _duplicate_reason_for_row(
    subscription: dict | None,
    result_episodes: set[tuple[int, int]],
    result_title_key: str,
    candidate_key: tuple[str, str] | None,
    row: dict[str, Any],
) -> str | None:
    """Compatibility helper for tests and older callers."""
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
    existing_title_key = compact_match_text(title_without_year(row.get("title")) or row.get("title"))
    return _similar_title_against_key(result_title_key, existing_title_key, result_episodes, existing_episodes)
