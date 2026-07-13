from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any

from app.db import db, utc_now

SOURCE_HEALTH_COOLDOWN_SECONDS = 600
SOURCE_HEALTH_FAIL_MARGIN = 3
SOURCE_HEALTH_SLOW_LATENCY_MS = 12000


def _source_stats_key(source_type: str, name: str, url: str = "") -> str:
    return f"{source_type}:{name or url or '\u672a\u77e5\u6e90'}"


def record_source_fetch(source_key: str, source_name: str, source_type: str, ok: bool, items: int = 0, latency_ms: int | None = None, error: str = "") -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO source_stats
            (source_key, source_name, source_type, success_count, fail_count, last_items, last_latency_ms,
             last_success_at, last_error_at, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_name = excluded.source_name,
                source_type = excluded.source_type,
                success_count = source_stats.success_count + excluded.success_count,
                fail_count = source_stats.fail_count + excluded.fail_count,
                last_items = excluded.last_items,
                last_latency_ms = excluded.last_latency_ms,
                last_success_at = COALESCE(excluded.last_success_at, source_stats.last_success_at),
                last_error_at = COALESCE(excluded.last_error_at, source_stats.last_error_at),
                last_error = CASE WHEN excluded.last_error != '' THEN excluded.last_error ELSE source_stats.last_error END,
                updated_at = excluded.updated_at
            """,
            (
                source_key,
                source_name,
                source_type,
                1 if ok else 0,
                0 if ok else 1,
                int(items or 0),
                latency_ms,
                now if ok else None,
                None if ok else now,
                str(error or "")[:500],
                now,
            ),
        )


def record_source_match(source: str | None) -> None:
    value = str(source or "").strip()
    if not value or ":" not in value:
        return
    source_type, source_name = value.split(":", 1)
    key = _source_stats_key(source_type, source_name)
    now = utc_now()
    with db() as conn:
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


def list_source_stats() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM source_stats ORDER BY updated_at DESC").fetchall()
    stats: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row[key] for key in row.keys()}
        _attach_source_summary(item)
        health = _source_health_from_item(item)
        item["degraded"] = bool(health.get("degraded"))
        item["degrade_reason"] = str(health.get("reason") or "")
        stats.append(item)
    return stats


def source_health_status(source_key: str) -> dict[str, Any]:
    """Return whether a source should be temporarily skipped after repeated failures or slow responses."""
    try:
        with db() as conn:
            row = conn.execute("SELECT * FROM source_stats WHERE source_key = ?", (source_key,)).fetchone()
    except sqlite3.OperationalError:
        return {"degraded": False, "reason": ""}
    if row is None:
        return {"degraded": False, "reason": ""}
    item = {key: row[key] for key in row.keys()}
    return _source_health_from_item(item)


def _attach_source_summary(item: dict[str, Any]) -> None:
    success = int(item.get("success_count") or 0)
    fail = int(item.get("fail_count") or 0)
    total = success + fail
    item["success_rate"] = round(success / total * 100) if total else 0


def _source_health_from_item(item: dict[str, Any]) -> dict[str, Any]:
    fail_count = int(item.get("fail_count") or 0)
    success_count = int(item.get("success_count") or 0)
    latency_ms = int(item.get("last_latency_ms") or 0)
    last_error_at = _parse_time(item.get("last_error_at"))
    last_success_at = _parse_time(item.get("last_success_at"))
    recent_error = _is_recent(last_error_at)
    if recent_error and fail_count - success_count >= SOURCE_HEALTH_FAIL_MARGIN:
        return {"degraded": True, "reason": "recent_failures", "fail_count": fail_count, "success_count": success_count}
    if latency_ms >= SOURCE_HEALTH_SLOW_LATENCY_MS and _slow_record_is_current(last_error_at, last_success_at):
        return {"degraded": True, "reason": "slow_source", "latency_ms": latency_ms}
    return {"degraded": False, "reason": ""}


def _is_recent(value: datetime | None) -> bool:
    return bool(value and datetime.now(timezone.utc) - value <= timedelta(seconds=SOURCE_HEALTH_COOLDOWN_SECONDS))


def _slow_record_is_current(last_error_at: datetime | None, last_success_at: datetime | None) -> bool:
    latest = max([item for item in (last_error_at, last_success_at) if item], default=None)
    return _is_recent(latest)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
