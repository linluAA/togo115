from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from app.db import add_log, db, row_to_dict, utc_now
from app.services.adapters.pan115 import SHARE_AVAILABLE, SHARE_UNAVAILABLE, SHARE_UNKNOWN, Pan115Adapter
from app.services.subscription_delivery import deliver_resource

RECHECK_INTERVAL_SECONDS = (30, 120, 300)
RECHECK_BATCH_LIMIT = 10


async def recheck_pending_115_resources(
    *,
    limit: int = RECHECK_BATCH_LIMIT,
    pan115_adapter_cls: type = Pan115Adapter,
    deliver: Callable[[int], Awaitable[bool]] = deliver_resource,
) -> dict[str, int]:
    resources = list_due_recheck_resources(limit)
    delivered = invalid = pending = failed = 0
    adapter = pan115_adapter_cls()
    for item in resources:
        state = await adapter.share_availability(str(item.get("url") or ""))
        if state == SHARE_AVAILABLE:
            delivered += await _deliver_available_recheck(item, deliver)
            continue
        if state == SHARE_UNAVAILABLE:
            invalid += _mark_recheck_invalid(int(item["id"]))
            continue
        if state == SHARE_UNKNOWN:
            pending += _mark_recheck_unknown(item)
            continue
        failed += _mark_recheck_unknown(item)
    if resources:
        add_log(
            "info",
            "subscription",
            "115 待复检资源处理完成",
            {"checked": len(resources), "delivered": delivered, "invalid": invalid, "pending": pending, "failed": failed},
        )
    return {"checked": len(resources), "delivered": delivered, "invalid": invalid, "pending": pending, "failed": failed}


def list_due_recheck_resources(limit: int = RECHECK_BATCH_LIMIT) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    with db() as conn:
        fetched = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title, s.target_path
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            WHERE r.status = 'pending_recheck'
            ORDER BY COALESCE(r.updated_at, r.created_at) ASC, r.id ASC
            LIMIT ?
            """,
            (max(1, min(int(limit or RECHECK_BATCH_LIMIT), 100)),),
        ).fetchall()
    for row in fetched:
        item = row_to_dict(row) or {}
        if _recheck_due(item, now):
            rows.append(item)
    return rows


async def _deliver_available_recheck(item: dict, deliver: Callable[[int], Awaitable[bool]]) -> int:
    resource_id = int(item["id"])
    _mark_recheck_pending_delivery(resource_id)
    if await deliver(resource_id):
        add_log("info", "subscription", "115 待复检资源已恢复可用并完成投递", {"resource_id": resource_id, "url": item.get("url")})
        return 1
    return 0


def _mark_recheck_pending_delivery(resource_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE resources SET status = 'pending', last_error = NULL, updated_at = ? WHERE id = ?",
            (utc_now(), resource_id),
        )


def _mark_recheck_invalid(resource_id: int) -> int:
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = 'link_invalid',
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("115 分享链接复检确认已失效", utc_now(), resource_id),
        )
    return 1


def _mark_recheck_unknown(item: dict) -> int:
    resource_id = int(item["id"])
    retry_count = int(item.get("retry_count") or 0) + 1
    status = "pending_recheck" if retry_count < len(RECHECK_INTERVAL_SECONDS) else "delivery_failed_retryable"
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = ?,
                retry_count = ?,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, retry_count, "115 分享链接有效性检测异常，等待复检重试", utc_now(), resource_id),
        )
    return 1


def _recheck_due(item: dict, now: datetime) -> bool:
    retry_count = int(item.get("retry_count") or 0)
    interval = RECHECK_INTERVAL_SECONDS[min(retry_count, len(RECHECK_INTERVAL_SECONDS) - 1)]
    updated_at = _parse_time(item.get("updated_at") or item.get("created_at"))
    return updated_at is None or now - updated_at >= timedelta(seconds=interval)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
