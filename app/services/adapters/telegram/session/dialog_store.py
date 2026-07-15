from __future__ import annotations

from typing import Any

from app.db import db, utc_now


def load_dialog_entity_rows(sources: list[str] | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        if sources:
            placeholders = ",".join("?" for _ in sources)
            rows = conn.execute(
                f"""
                SELECT source, peer_id, entity_id, access_hash, username, title, entity_type, updated_at
                FROM telegram_dialog_entities
                WHERE source IN ({placeholders})
                """,
                [str(item) for item in sources],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT source, peer_id, entity_id, access_hash, username, title, entity_type, updated_at
                FROM telegram_dialog_entities
                """
            ).fetchall()
    return [dict(row) for row in rows]


def upsert_dialog_entity(
    *,
    source: str,
    peer_id: str,
    entity_id: str | None = None,
    access_hash: str | None = None,
    username: str | None = None,
    title: str | None = None,
    entity_type: str | None = None,
) -> None:
    source_value = str(source or "").strip()
    peer_value = str(peer_id or "").strip()
    if not source_value or not peer_value:
        return
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO telegram_dialog_entities
                (source, peer_id, entity_id, access_hash, username, title, entity_type, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                peer_id = excluded.peer_id,
                entity_id = excluded.entity_id,
                access_hash = excluded.access_hash,
                username = excluded.username,
                title = excluded.title,
                entity_type = excluded.entity_type,
                updated_at = excluded.updated_at
            """,
            (
                source_value,
                peer_value,
                str(entity_id or "") or None,
                str(access_hash or "") or None,
                str(username or "") or None,
                str(title or "") or None,
                str(entity_type or "") or None,
                now,
            ),
        )


def upsert_dialog_entities(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    now = utc_now()
    payload = []
    for row in rows:
        source_value = str(row.get("source") or "").strip()
        peer_value = str(row.get("peer_id") or "").strip()
        if not source_value or not peer_value:
            continue
        payload.append(
            {
                "source": source_value,
                "peer_id": peer_value,
                "entity_id": str(row.get("entity_id") or "") or None,
                "access_hash": str(row.get("access_hash") or "") or None,
                "username": str(row.get("username") or "") or None,
                "title": str(row.get("title") or "") or None,
                "entity_type": str(row.get("entity_type") or "") or None,
                "updated_at": now,
            }
        )
    if not payload:
        return 0
    with db() as conn:
        conn.executemany(
            """
            INSERT INTO telegram_dialog_entities
                (source, peer_id, entity_id, access_hash, username, title, entity_type, updated_at)
            VALUES
                (:source, :peer_id, :entity_id, :access_hash, :username, :title, :entity_type, :updated_at)
            ON CONFLICT(source) DO UPDATE SET
                peer_id = excluded.peer_id,
                entity_id = excluded.entity_id,
                access_hash = excluded.access_hash,
                username = excluded.username,
                title = excluded.title,
                entity_type = excluded.entity_type,
                updated_at = excluded.updated_at
            """,
            payload,
        )
    return len(payload)
