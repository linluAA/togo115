from __future__ import annotations

import os
import socket
from functools import lru_cache
from typing import Any

from app.db import db, json_dumps, json_loads, row_to_dict, utc_now


@lru_cache(maxsize=1)
def worker_instance_id() -> str:
    """Stable-ish worker identity for multi-instance observability."""
    explicit = (os.environ.get("TOGO115_WORKER_ID") or os.environ.get("HOSTNAME") or "").strip()
    if explicit:
        return explicit[:120]
    host = socket.gethostname() or "worker"
    return f"{host}:{os.getpid()}"[:120]


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


def touch_job_heartbeat(job_id: int, worker_id: str | None = None) -> None:
    """Refresh heartbeat for a long-running job (multi-instance liveness)."""
    now = utc_now()
    worker = (worker_id or worker_instance_id())[:120]
    with db() as conn:
        conn.execute(
            """
            UPDATE background_jobs
            SET heartbeat_at = ?, worker_id = COALESCE(?, worker_id), updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (now, worker, now, int(job_id)),
        )


def job_queue_stats() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM background_jobs GROUP BY status"
        ).fetchall()
        running_workers = conn.execute(
            """
            SELECT COUNT(DISTINCT worker_id) AS c
            FROM background_jobs
            WHERE status = 'running' AND worker_id IS NOT NULL AND worker_id != ''
            """
        ).fetchone()
    counts: dict[str, Any] = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for row in rows:
        key = str(row["status"] if hasattr(row, "keys") else row[0])
        val = int(row["c"] if hasattr(row, "keys") else row[1])
        if key in counts:
            counts[key] = val
    counts["total"] = int(counts["queued"]) + int(counts["running"]) + int(counts["done"]) + int(counts["failed"])
    try:
        counts["running_workers"] = int(running_workers["c"] if hasattr(running_workers, "keys") else running_workers[0] or 0)
    except Exception:
        counts["running_workers"] = 0
    counts["worker_id"] = worker_instance_id()
    try:
        with db() as conn:
            row = conn.execute(
                """
                SELECT MIN(COALESCE(heartbeat_at, started_at, updated_at)) AS oldest
                FROM background_jobs
                WHERE status = 'running'
                """
            ).fetchone()
            counts["oldest_running_heartbeat_at"] = (
                row["oldest"] if row is not None and hasattr(row, "keys") else (row[0] if row else None)
            )
    except Exception:
        counts["oldest_running_heartbeat_at"] = None
    return counts


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

def claim_next_job(kinds: list[str] | None = None, worker_id: str | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest queued job and mark it running."""
    now = utc_now()
    worker = (worker_id or worker_instance_id())[:120]
    with db() as conn:
        # Exclusive transaction reduces double-claim risk under multi-worker.
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception:
            pass
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            row = conn.execute(
                f"""
                SELECT * FROM background_jobs
                WHERE status = 'queued' AND kind IN ({placeholders})
                ORDER BY id ASC
                LIMIT 1
                """,
                tuple(kinds),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM background_jobs
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        item = normalize_job(row_to_dict(row))
        updated = conn.execute(
            """
            UPDATE background_jobs
            SET status = 'running',
                started_at = COALESCE(started_at, ?),
                heartbeat_at = ?,
                worker_id = ?,
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now, now, worker, now, item["id"]),
        )
        if updated.rowcount != 1:
            return None
        item["status"] = "running"
        item["started_at"] = item.get("started_at") or now
        item["heartbeat_at"] = now
        item["worker_id"] = worker
        item["updated_at"] = now
        return item


def requeue_stale_running_jobs(max_age_seconds: int = 1800) -> int:
    """Requeue long-running jobs whose heartbeat stopped (worker likely died)."""
    now = utc_now()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, started_at, heartbeat_at, updated_at FROM background_jobs WHERE status = 'running'"
        ).fetchall()
        count = 0
        for row in rows:
            stamp = str(row["heartbeat_at"] or row["started_at"] or row["updated_at"] or "")
            try:
                from datetime import datetime, timezone

                stamp_dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if stamp_dt.tzinfo is None:
                    stamp_dt = stamp_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - stamp_dt).total_seconds()
            except Exception:
                continue
            if age < max_age_seconds:
                continue
            conn.execute(
                """
                UPDATE background_jobs
                SET status = 'queued', started_at = NULL, heartbeat_at = NULL, worker_id = NULL,
                    error = COALESCE(error, ?), updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                ("stale running job requeued (heartbeat timeout)", now, int(row["id"])),
            )
            count += 1
        return count
