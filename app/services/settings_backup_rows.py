from __future__ import annotations

from typing import Any

from app.db import json_dumps, json_loads, row_to_dict


def _serialize_subscription(row: Any) -> dict[str, Any]:
    item = row_to_dict(row) or {}
    return {
        **item,
        "keywords": json_loads(row["keywords"], []),
        "quality_rules": json_loads(row["quality_rules"], {}),
        "tmdb_seasons": json_loads(row["tmdb_seasons"], []),
        "emby_episode_keys": json_loads(row["emby_episode_keys"], []),
    }


def _subscription_values(
    item: dict[str, Any],
    title: str,
    media_type: str,
    tmdb_id: int | None,
    now: str,
) -> tuple[Any, ...]:
    return (
        title,
        media_type,
        tmdb_id,
        item.get("poster_url"),
        item.get("overview"),
        item.get("release_year"),
        json_dumps(item.get("keywords") or [title]),
        json_dumps(item.get("quality_rules") or {}),
        item.get("delivery_mode") or "115",
        item.get("target_path"),
        int(item.get("emby_count") or 0),
        int(item.get("tmdb_total_count") or 0),
        json_dumps(item.get("tmdb_seasons") or []),
        json_dumps(item.get("emby_episode_keys") or []),
        1 if item.get("in_library") else 0,
        item.get("status") or "active",
        item.get("completed_at"),
        item.get("last_checked_at"),
        now,
    )


def _parse_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
