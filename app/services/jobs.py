from __future__ import annotations

from typing import Any

from app.db import db, json_dumps, json_loads, row_to_dict, utc_now


def create_job(kind: str, target_id: int | None = None, payload: dict[str, Any] | None = None) -> int:
    now = utc_now()
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO background_jobs
            (kind, target_id, status, payload, result, error, created_at, started_at, finished_at, updated_at)
            VALUES (?, ?, 'queued', ?, NULL, NULL, ?, NULL, NULL, ?)
            """,
            (kind, target_id, json_dumps(payload or {}), now, now),
        )
        return int(cursor.lastrowid)


def mark_job_running(job_id: int) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            UPDATE background_jobs
            SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )


def mark_job_done(job_id: int, result: dict[str, Any] | None = None) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            UPDATE background_jobs
            SET status = 'done', result = ?, error = NULL, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json_dumps(result or {}), now, now, job_id),
        )


def mark_job_failed(job_id: int, error: str, result: dict[str, Any] | None = None) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            UPDATE background_jobs
            SET status = 'failed', result = ?, error = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json_dumps(result or {}), str(error)[:1000], now, now, job_id),
        )


def latest_job(kind: str, target_id: int | None = None) -> dict[str, Any] | None:
    with db() as conn:
        if target_id is None:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE kind = ? ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM background_jobs WHERE kind = ? AND target_id = ? ORDER BY id DESC LIMIT 1",
                (kind, target_id),
            ).fetchone()
    item = row_to_dict(row)
    return normalize_job(item) if item else None


def list_jobs(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    with db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM background_jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM background_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [normalize_job(row_to_dict(row) or {}) for row in rows]


def normalize_job(item: dict[str, Any]) -> dict[str, Any]:
    item["payload"] = json_loads(item.get("payload"), {})
    item["result"] = json_loads(item.get("result"), {})
    return item
