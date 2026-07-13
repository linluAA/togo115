from __future__ import annotations

from typing import Any

from app.db import json_dumps
from app.services.settings_backup_rows import _parse_optional_int, _subscription_values


def _upsert_setting(conn: Any, key: str, value: dict[str, Any], now: str) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json_dumps(value), now),
    )


def _upsert_subscription(conn: Any, item: dict[str, Any], now: str) -> None:
    title = str(item.get("title") or "").strip()
    media_type = item.get("media_type") if item.get("media_type") in ("tv", "movie") else "tv"
    tmdb_id = _parse_optional_int(item.get("tmdb_id"))
    existing = _find_existing_subscription(conn, media_type, title, tmdb_id)
    values = _subscription_values(item, title, media_type, tmdb_id, now)
    if existing:
        _update_subscription(conn, existing["id"], values)
        return
    _insert_subscription(conn, values, now)


def _find_existing_subscription(conn: Any, media_type: str, title: str, tmdb_id: int | None) -> Any:
    if tmdb_id:
        existing = conn.execute(
            "SELECT id FROM subscriptions WHERE media_type = ? AND tmdb_id = ?",
            (media_type, tmdb_id),
        ).fetchone()
        if existing:
            return existing
    return conn.execute(
        "SELECT id FROM subscriptions WHERE media_type = ? AND title = ? AND tmdb_id IS NULL",
        (media_type, title),
    ).fetchone()


def _update_subscription(conn: Any, subscription_id: int, values: tuple[Any, ...]) -> None:
    conn.execute(
        """
        UPDATE subscriptions
        SET title = ?, media_type = ?, tmdb_id = ?, poster_url = ?, overview = ?, release_year = ?,
            keywords = ?, quality_rules = ?, delivery_mode = ?, target_path = ?, emby_count = ?,
            tmdb_total_count = ?, tmdb_seasons = ?, emby_episode_keys = ?, in_library = ?,
            status = ?, completed_at = ?, last_checked_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (*values, subscription_id),
    )


def _insert_subscription(conn: Any, values: tuple[Any, ...], now: str) -> None:
    conn.execute(
        """
        INSERT INTO subscriptions
        (title, media_type, tmdb_id, poster_url, overview, release_year, keywords, quality_rules,
         delivery_mode, target_path, emby_count, tmdb_total_count, tmdb_seasons, emby_episode_keys,
         in_library, status, completed_at, last_checked_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*values, now),
    )
