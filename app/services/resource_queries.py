from __future__ import annotations

from app.db import add_log, db, row_to_dict


def list_recent_resources(limit: int = 80, offset: int = 0) -> list[dict]:
    limit = max(1, min(int(limit or 80), 200))
    offset = max(0, int(offset or 0))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            WHERE r.status NOT IN ('skipped', 'matched_not_needed')
            ORDER BY r.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def delete_resources(ids: list[int]) -> int:
    resource_ids = sorted({int(item) for item in ids if int(item) > 0})
    if not resource_ids:
        return 0
    placeholders = ",".join("?" for _ in resource_ids)
    with db() as conn:
        cursor = conn.execute(f"DELETE FROM resources WHERE id IN ({placeholders})", resource_ids)
        deleted = int(cursor.rowcount or 0)
    add_log("info", "subscription", "已删除最近发现的资源", {"requested": len(resource_ids), "deleted": deleted})
    return deleted


def clear_resources() -> int:
    with db() as conn:
        cursor = conn.execute("DELETE FROM resources")
        deleted = int(cursor.rowcount or 0)
    add_log("info", "subscription", "已清空最近发现的资源", {"deleted": deleted})
    return deleted
