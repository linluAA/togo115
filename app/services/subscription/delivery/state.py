from __future__ import annotations

import asyncio
from typing import Any

from app.db import db, row_to_dict, utc_now
from app.services.subscription.resource.resources import resource_dedupe_key


_delivery_locks: dict[tuple[int, tuple[str, str]], asyncio.Lock] = {}


def _load_resource_for_delivery(resource_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT r.*, s.target_path FROM resources r JOIN subscriptions s ON s.id = r.subscription_id WHERE r.id = ?",
            (resource_id,),
        ).fetchone()


def _delivery_lock(dedupe_key: tuple[str, str]) -> asyncio.Lock:
    lock_key = (id(asyncio.get_running_loop()), dedupe_key)
    lock = _delivery_locks.get(lock_key)
    if lock is None:
        lock = asyncio.Lock()
        _delivery_locks[lock_key] = lock
    return lock


def _existing_effective_delivery(resource) -> dict[str, Any] | None:
    candidate_key = resource_dedupe_key(resource["url"] or "")
    if not candidate_key:
        return None
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, url, status
            FROM resources
            WHERE id != ? AND status = 'delivered'
            ORDER BY id ASC
            """,
            (resource["id"],),
        ).fetchall()
    for row in rows:
        item = row_to_dict(row) or {}
        if resource_dedupe_key(item.get("url") or "") == candidate_key:
            return item
    return None


def _mark_resource_duplicate_delivered(resource_id: int, existing: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = 'delivered',
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), resource_id),
        )


def _update_resource_delivery_status(resource_id: int, ok: bool, error_message: str) -> None:
    failed_status = _delivery_failed_status(error_message)
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = ?,
                retry_count = CASE WHEN ? THEN retry_count ELSE retry_count + 1 END,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("delivered" if ok else failed_status, 1 if ok else 0, None if ok else error_message[:500], utc_now(), resource_id),
        )


def _delivery_failed_status(error_message: str) -> str:
    text = str(error_message or "").casefold()
    if any(word in text for word in ("\u5f85\u590d\u68c0", "\u5f85\u8907\u6aa2", "recheck", "unknown")):
        return "pending_recheck"
    if any(
        word in text
        for word in (
            "\u683c\u5f0f\u65e0\u6548",
            "\u683c\u5f0f\u7121\u6548",
            "\u94fe\u63a5\u4e3a\u7a7a",
            "\u93c8\u63a5\u70ba\u7a7a",
            "\u5931\u6548",
            "\u4e0d\u53ef\u7528",
            "invalid",
            "unavailable",
        )
    ):
        return "link_invalid"
    if any(word in text for word in ("timeout", "timed out", "network", "connection", "proxy", "tls", "ssl", "temporar", "rate", "429", "500", "502", "503", "504")):
        return "delivery_failed_retryable"
    return "delivery_failed_final"
