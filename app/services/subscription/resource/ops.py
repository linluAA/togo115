from __future__ import annotations

import sqlite3
from typing import Any

from app.db import add_log, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.link_downloads import is_valid_download_link
from app.services.subscription.resource.duplicate import resource_already_exists
from app.services.subscription.resource.fallback import (
    best_fallback_result,
    fallback_blocked_by_primary_resource,
    fallback_result_candidates,
    results_may_match_subscription,
    subscription_115_resources,
)
from app.services.subscription.resource.matching import matching_results, unmatched_results
from app.services.subscription.match.matching import (
    result_debug_payload,
)
from app.services.subscription.resource.resources import (
    canonical_115_url as _canonical_115_url,
    existing_resource_rows as existing_resource_rows,
)
from app.services.subscription.resource.guard import resource_allowed_for_subscription


def _insert_resource(
    conn,
    subscription_id: int,
    result: SearchResult,
    subscription: dict | None = None,
    existing_rows: list[dict[str, Any]] | None = None,
) -> dict | None:
    canonical_url = _canonical_115_url(result.url)
    if canonical_url:
        result.url = canonical_url
    if not is_valid_download_link(result.url):
        add_log(
            "debug",
            "subscription",
            "资源链接格式无效，跳过保存",
            {"id": subscription_id, "url": result.url, "title": str(getattr(result, "title", "") or "")[:120]},
        )
        return None
    if not resource_allowed_for_subscription(subscription, result, scope="save"):
        return None
    duplicate_reason = resource_already_exists(conn, subscription_id, result, subscription, existing_rows)
    if duplicate_reason:
        add_log(
            "debug",
            "subscription",
            "资源链接已存在或集数重复，跳过推送",
            {"id": subscription_id, "url": result.url, "reason": duplicate_reason},
        )
        return None
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO resources (subscription_id, source, title, url, message_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (subscription_id, result.source, result.title, result.url, result.message_id, utc_now(), utc_now()),
    )
    if cursor.rowcount == 0:
        return None
    if existing_rows is not None:
        existing_rows.insert(0, {"title": result.title, "url": result.url, "status": "pending"})
    return {**result.__dict__, "resource_id": cursor.lastrowid}


def _record_source_match_with_conn(conn: sqlite3.Connection, source: str | None) -> None:
    value = str(source or "").strip()
    if not value or ":" not in value:
        return
    source_type, source_name = value.split(":", 1)
    key = f"{source_type}:{source_name or '订阅源'}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO source_stats
        (source_key, source_name, source_type, match_count, updated_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_name = excluded.source_name,
            source_type = excluded.source_type,
            match_count = source_stats.match_count + 1,
            updated_at = excluded.updated_at
        """,
        (key, source_name, source_type, now),
    )


def _insert_resource_automatic(
    conn: sqlite3.Connection,
    subscription: dict,
    result: SearchResult,
    existing_rows: list[dict[str, Any]] | None = None,
) -> dict | None:
    item = _insert_resource(conn, int(subscription["id"]), result, subscription, existing_rows)
    if item:
        _record_source_match_with_conn(conn, result.source)
    return item
def insert_resource_safely(
    conn: sqlite3.Connection,
    subscription: dict,
    result: SearchResult,
    existing_rows: list[dict[str, Any]] | None = None,
) -> dict | None:
    try:
        return _insert_resource_automatic(conn, subscription, result, existing_rows)
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "资源保存失败，已跳过单条结果",
            {"id": subscription.get("id"), **result_debug_payload(result), "error": str(exc)},
        )
        return None


