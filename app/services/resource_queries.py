from __future__ import annotations

from collections import OrderedDict
from typing import Any

from app.db import add_log, db, row_to_dict
from app.services.subscription.episode.parser import episode_keys_from_text_for_subscription
from app.services.subscription.episode.summary import episode_range_labels
from app.services.subscription.resource.resources import resource_dedupe_key


def list_recent_resources(limit: int = 80, offset: int = 0) -> list[dict]:
    """Return recent resources with same-sub hash/episode rows merged for display."""
    limit = max(1, min(int(limit or 80), 200))
    offset = max(0, int(offset or 0))
    fetch_limit = min(1000, max(limit * 8, offset * 4 + 80))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            WHERE r.status NOT IN ('skipped', 'matched_not_needed')
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (fetch_limit,),
        ).fetchall()
    items = [row_to_dict(row) or {} for row in rows]
    merged = merge_resource_rows(items)
    return merged[offset : offset + limit]


def merge_resource_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge same-subscription resources by magnet/115 hash, then by episode set."""
    by_hash: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
    for item in items:
        key = _hash_group_key(item)
        if key in by_hash:
            by_hash[key] = _merge_group(by_hash[key], item)
        else:
            by_hash[key] = _as_group(item)

    by_episode: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
    for item in by_hash.values():
        key = _episode_group_key(item)
        if key is None:
            by_episode[("row", item.get("id"))] = item
            continue
        if key in by_episode:
            by_episode[key] = _merge_group(by_episode[key], item)
        else:
            by_episode[key] = item
    return list(by_episode.values())


def _hash_group_key(item: dict[str, Any]) -> tuple[Any, ...]:
    sub_id = int(item.get("subscription_id") or 0)
    dedupe = resource_dedupe_key(str(item.get("url") or ""))
    if dedupe:
        return ("hash", sub_id, dedupe[0], dedupe[1])
    return ("id", sub_id, int(item.get("id") or 0))


def _episode_group_key(item: dict[str, Any]) -> tuple[Any, ...] | None:
    sub_id = int(item.get("subscription_id") or 0)
    if not sub_id:
        return None
    status = str(item.get("status") or "").casefold()
    if status not in {"delivered", "pending"}:
        return None
    episodes = _resource_episodes(item)
    if not episodes:
        return None
    return ("ep", sub_id, status, tuple(sorted(episodes)))


def _resource_episodes(item: dict[str, Any]) -> set[tuple[int, int]]:
    text = "\n".join(
        str(part or "")
        for part in (
            item.get("title"),
            item.get("subscription_title"),
            item.get("url"),
            item.get("message_id"),
        )
    )
    return episode_keys_from_text_for_subscription(
        {
            "id": item.get("subscription_id"),
            "title": item.get("subscription_title") or item.get("title"),
        },
        text,
    )


def _as_group(item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item)
    episodes = sorted(_resource_episodes(row))
    row["group_count"] = 1
    row["group_ids"] = [int(row["id"])] if row.get("id") is not None else []
    row["group_episode_keys"] = [f"{season}x{episode}" for season, episode in episodes]
    row["group_episode_labels"] = episode_range_labels(episodes)
    base = row.get("subscription_title") or row.get("title") or "资源"
    if row["group_episode_labels"] and not _title_looks_like_episode(row.get("title") or ""):
        labels = " / ".join(row["group_episode_labels"][:3])
        row["display_title"] = f"{base} · {labels}"
    else:
        row["display_title"] = base
    return row


def _merge_group(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    primary = _as_group(primary) if "group_count" not in primary else dict(primary)
    secondary = _as_group(secondary)
    if _status_rank(secondary.get("status")) > _status_rank(primary.get("status")) or (
        _status_rank(secondary.get("status")) == _status_rank(primary.get("status"))
        and int(secondary.get("id") or 0) > int(primary.get("id") or 0)
    ):
        primary, secondary = secondary, primary
        primary = _as_group(primary)
        secondary = _as_group(secondary)

    ids: list[int] = []
    for value in list(primary.get("group_ids") or []) + list(secondary.get("group_ids") or []):
        number = int(value)
        if number not in ids:
            ids.append(number)

    episodes: set[tuple[int, int]] = set()
    for key in list(primary.get("group_episode_keys") or []) + list(secondary.get("group_episode_keys") or []):
        if isinstance(key, str) and "x" in key:
            season_s, episode_s = key.split("x", 1)
            try:
                episodes.add((int(season_s), int(episode_s)))
            except ValueError:
                pass
    episodes.update(_resource_episodes(primary))
    episodes.update(_resource_episodes(secondary))

    primary["group_ids"] = ids
    primary["group_count"] = len(ids)
    primary["group_episode_keys"] = [f"{season}x{episode}" for season, episode in sorted(episodes)]
    primary["group_episode_labels"] = episode_range_labels(sorted(episodes))
    base = primary.get("subscription_title") or primary.get("title") or "资源"
    if primary["group_episode_labels"]:
        labels = " / ".join(primary["group_episode_labels"][:3])
        suffix = f" · {labels}"
        if primary["group_count"] > 1:
            suffix += f" · {primary['group_count']}条"
        primary["display_title"] = f"{base}{suffix}"
    elif primary["group_count"] > 1:
        primary["display_title"] = f"{base} · {primary['group_count']}条"
    else:
        primary["display_title"] = base
    if not primary.get("last_error") and secondary.get("last_error"):
        if _status_rank(primary.get("status")) <= _status_rank("failed"):
            primary["last_error"] = secondary.get("last_error")
    return primary


def _status_rank(status: str | None) -> int:
    value = str(status or "").casefold()
    order = {
        "delivered": 100,
        "pending": 80,
        "pending_recheck": 70,
        "delivery_failed_retryable": 60,
        "failed": 50,
        "delivery_failed_final": 40,
        "link_invalid": 30,
        "skipped": 10,
        "matched_not_needed": 5,
    }
    return order.get(value, 0)


def _title_looks_like_episode(title: str) -> bool:
    text = str(title or "")
    return any(token in text for token in ("S0", "S1", "E0", "E1", "EP", "Ep", "ep"))


def delete_resources(ids: list[int]) -> int:
    resource_ids = sorted({int(item) for item in ids if int(item) > 0})
    if not resource_ids:
        return 0
    placeholders = ",".join("?" for _ in resource_ids)
    with db() as conn:
        cursor = conn.execute(f"DELETE FROM resources WHERE id IN ({placeholders})", resource_ids)
        deleted = int(cursor.rowcount or 0)
    add_log("info", "subscription", "deleted recent resources", {"requested": len(resource_ids), "deleted": deleted})
    return deleted


def clear_resources() -> int:
    with db() as conn:
        cursor = conn.execute("DELETE FROM resources")
        deleted = int(cursor.rowcount or 0)
    add_log("info", "subscription", "cleared recent resources", {"deleted": deleted})
    return deleted
