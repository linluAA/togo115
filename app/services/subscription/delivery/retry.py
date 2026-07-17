from __future__ import annotations

from typing import Any, Callable

from app.db import add_log, db, row_to_dict, utc_now
from app.services.subscription.delivery.state import classify_delivery_failure


def list_failed_resources(limit: int = 100) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title, s.poster_url AS subscription_poster_url
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            WHERE r.status IN ('failed', 'delivery_failed_retryable', 'delivery_failed_final')
            ORDER BY r.updated_at DESC, r.id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 100), 500)),),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]

async def retry_failed_resources(limit: int, deliver: Callable[[int], Any]) -> dict:
    """Retry failed deliveries with classification-aware selection and soft backoff."""
    candidates = select_retryable_failed_resources(limit)
    ok = 0
    failed_count = 0
    skipped = 0
    by_kind: dict[str, int] = {}
    for item in candidates:
        kind = str(item.get("failure_kind") or "temporary")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if item.get("skip_reason"):
            skipped += 1
            continue
        if await deliver(int(item["id"])):
            ok += 1
        else:
            failed_count += 1
    return {
        "ok": True,
        "retried": len(candidates) - skipped,
        "delivered": ok,
        "failed": failed_count,
        "skipped": skipped,
        "by_kind": by_kind,
    }


# Soft backoff windows by failure class (seconds). Invalid links are never auto-retried.
RETRY_BACKOFF_SECONDS = {
    "timeout": (60, 180, 600, 1800),
    "network": (90, 300, 900, 1800),
    "temporary": (120, 600, 1800, 3600),
    "rate": (300, 900, 1800, 3600),
    "flood": (600, 1800, 3600, 7200),
    "auth": (900, 1800, 3600, 7200),
    "recheck": (120, 600, 1800, 7200),
}
RETRYABLE_STATUSES = {
    "failed",
    "delivery_failed_retryable",
    "delivery_failed_final",
    "pending_recheck",
}
NON_RETRY_KINDS = {"invalid", "final"}

def select_retryable_failed_resources(limit: int = 20) -> list[dict]:
    """Pick failed resources due for retry; skip invalid and not-yet-due backoff rows."""
    from datetime import datetime, timezone

    rows = list_failed_resources(max(1, min(int(limit or 20) * 4, 200)))
    now = datetime.now(timezone.utc)
    selected: list[dict] = []
    for item in rows:
        kind = classify_delivery_failure(item.get("last_error") or "")
        status = str(item.get("status") or "").casefold()
        if status == "link_invalid" or kind == "invalid":
            item = {**item, "failure_kind": "invalid", "skip_reason": "invalid_link"}
            selected.append(item)
            continue
        if status == "delivery_failed_final" and kind == "final":
            # Allow a few manual retries on finals, but not endless auto spam.
            if int(item.get("retry_count") or 0) >= 3:
                item = {**item, "failure_kind": kind, "skip_reason": "final_exhausted"}
                selected.append(item)
                continue
        if not _retry_due(item, kind, now):
            item = {**item, "failure_kind": kind, "skip_reason": "backoff"}
            selected.append(item)
            continue
        selected.append({**item, "failure_kind": kind, "skip_reason": ""})
        if sum(1 for row in selected if not row.get("skip_reason")) >= max(1, min(int(limit or 20), 100)):
            break
    # Return only actionable + summary skips for metrics; deliver loop skips skip_reason rows.
    return selected

def _retry_due(item: dict, kind: str, now) -> bool:
    from datetime import datetime, timedelta, timezone

    if kind in NON_RETRY_KINDS:
        return False
    retries = max(0, int(item.get("retry_count") or 0))
    windows = RETRY_BACKOFF_SECONDS.get(kind) or RETRY_BACKOFF_SECONDS["temporary"]
    delay = windows[min(retries, len(windows) - 1)]
    raw = str(item.get("updated_at") or item.get("created_at") or "").strip()
    if not raw:
        return True
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return stamp + timedelta(seconds=delay) <= now
