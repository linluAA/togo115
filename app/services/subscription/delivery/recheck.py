from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

from app.db import add_log, db, row_to_dict, utc_now
from app.services.adapters.pan115 import SHARE_AVAILABLE, SHARE_UNAVAILABLE, SHARE_UNKNOWN, Pan115Adapter
from app.services.subscription.delivery.service import deliver_resource

# Longer progressive backoff: 2m / 10m / 30m / 2h
RECHECK_INTERVAL_SECONDS = (120, 600, 1800, 7200)
RECHECK_BATCH_LIMIT = 10
RECHECK_CONCURRENCY = 3


async def recheck_pending_115_resources(
    *,
    limit: int = RECHECK_BATCH_LIMIT,
    pan115_adapter_cls: type = Pan115Adapter,
    deliver: Callable[[int], Awaitable[bool]] = deliver_resource,
) -> dict[str, int]:
    resources = list_due_recheck_resources(limit)
    if not resources:
        return {"checked": 0, "delivered": 0, "invalid": 0, "pending": 0, "failed": 0, "shared_invalid": 0}

    adapter = pan115_adapter_cls()
    semaphore = asyncio.Semaphore(RECHECK_CONCURRENCY)
    checked_share_codes: dict[str, str] = {}
    share_lock = asyncio.Lock()

    async def process(item: dict) -> dict[str, int]:
        url = str(item.get("url") or "")
        share_code = _share_code_from_url(url)
        async with share_lock:
            cached_state = checked_share_codes.get(share_code) if share_code else None
        if cached_state is not None:
            return await _apply_known_state(item, cached_state, deliver, shared=True)

        async with semaphore:
            state = await adapter.share_availability(url)
        if share_code:
            async with share_lock:
                checked_share_codes[share_code] = state
        result = await _apply_known_state(item, state, deliver, shared=False)
        if state == SHARE_UNAVAILABLE and share_code:
            result["shared_invalid"] = _mark_invalid_by_share_code(share_code, exclude_id=int(item["id"]))
        return result

    outcomes = await asyncio.gather(*(process(item) for item in resources))
    summary = {"checked": len(resources), "delivered": 0, "invalid": 0, "pending": 0, "failed": 0, "shared_invalid": 0}
    for item in outcomes:
        for key in ("delivered", "invalid", "pending", "failed", "shared_invalid"):
            summary[key] += int(item.get(key) or 0)
    add_log("info", "subscription", "115 \u5f85\u590d\u68c0\u8d44\u6e90\u5904\u7406\u5b8c\u6210", summary)
    return summary


async def _apply_known_state(
    item: dict,
    state: str,
    deliver: Callable[[int], Awaitable[bool]],
    *,
    shared: bool,
) -> dict[str, int]:
    if state == SHARE_AVAILABLE:
        return {"delivered": await _deliver_available_recheck(item, deliver), "invalid": 0, "pending": 0, "failed": 0, "shared_invalid": 0}
    if state == SHARE_UNAVAILABLE:
        count = _mark_recheck_invalid(int(item["id"]))
        return {
            "delivered": 0,
            "invalid": 0 if shared else count,
            "pending": 0,
            "failed": 0,
            "shared_invalid": count if shared else 0,
        }
    count = _mark_recheck_unknown(item)
    if state == SHARE_UNKNOWN:
        return {"delivered": 0, "invalid": 0, "pending": count, "failed": 0, "shared_invalid": 0}
    return {"delivered": 0, "invalid": 0, "pending": 0, "failed": count, "shared_invalid": 0}


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
        add_log(
            "info",
            "subscription",
            "115 \u5f85\u590d\u68c0\u8d44\u6e90\u5df2\u6062\u590d\u53ef\u7528\u5e76\u5b8c\u6210\u6295\u9012",
            {"resource_id": resource_id, "url": item.get("url")},
        )
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
            ("115 \u5206\u4eab\u94fe\u63a5\u590d\u68c0\u786e\u8ba4\u5df2\u5931\u6548", utc_now(), resource_id),
        )
    return 1


def _mark_invalid_by_share_code(share_code: str, *, exclude_id: int) -> int:
    code = str(share_code or "").strip()
    if not code:
        return 0
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, url
            FROM resources
            WHERE status = 'pending_recheck'
              AND id != ?
            """,
            (exclude_id,),
        ).fetchall()
        ids: list[int] = []
        for row in rows:
            item = row_to_dict(row) or {}
            if _share_code_from_url(str(item.get("url") or "")) == code:
                ids.append(int(item["id"]))
        if not ids:
            return 0
        now = utc_now()
        conn.executemany(
            """
            UPDATE resources
            SET status = 'link_invalid',
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            [("115 \u5206\u4eab\u94fe\u63a5\u590d\u68c0\u786e\u8ba4\u5df2\u5931\u6548\uff08\u540c\u6e90\u5171\u4eab\uff09", now, item_id) for item_id in ids],
        )
        return len(ids)


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
            (
                status,
                retry_count,
                "115 \u5206\u4eab\u94fe\u63a5\u6709\u6548\u6027\u68c0\u6d4b\u5f02\u5e38\uff0c\u7b49\u5f85\u590d\u68c0\u91cd\u8bd5",
                utc_now(),
                resource_id,
            ),
        )
    return 1


def _recheck_due(item: dict, now: datetime) -> bool:
    retry_count = int(item.get("retry_count") or 0)
    interval = RECHECK_INTERVAL_SECONDS[min(retry_count, len(RECHECK_INTERVAL_SECONDS) - 1)]
    updated_at = _parse_time(item.get("updated_at") or item.get("created_at"))
    return updated_at is None or now - updated_at >= timedelta(seconds=interval)


def _share_code_from_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    path = (parsed.path or "").rstrip("/")
    if "/s/" in path:
        code = path.rsplit("/s/", 1)[-1].split("/")[0]
        return code.casefold()
    query = parse_qs(parsed.query or "")
    for key in ("share_code", "sharecode", "code"):
        values = query.get(key) or []
        if values and values[0]:
            return str(values[0]).casefold()
    return ""


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
