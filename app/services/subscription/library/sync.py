from __future__ import annotations

from typing import Any

from app.db import add_log, db, json_dumps, utc_now
from app.services.adapters.media import TmdbAdapter
from app.services.subscription.library.match import _emby_configured
from app.services.subscription.library.snapshot import _library_snapshot_or_none
from app.services.subscription.library.state import (
    _library_state,
    _series_episode_count,
    _series_episode_count_by_name,
)
from app.services.subscription.match.matching import _compact_match_text, _json_episode_key


async def sync_subscription_list_with_emby(subscriptions: list[dict], force: bool = False) -> dict:
    if not subscriptions:
        return {"ok": True, "updated": 0, "matched": 0}
    if not _emby_configured():
        return {"ok": True, "updated": 0, "matched": 0, "skipped": "emby_not_configured"}
    try:
        snapshot = await _library_snapshot_or_none(force=force)
        if snapshot is None or "__failed__" in snapshot:
            return {"ok": False, "updated": 0, "matched": 0, "error": "emby_snapshot_failed"}
    except Exception as exc:
        add_log("error", "emby", "Emby 媒体库快照同步失败", {"error": str(exc)})
        return {"ok": False, "updated": 0, "matched": 0, "error": str(exc)}

    return await sync_subscriptions_with_emby_snapshot(subscriptions, snapshot)


async def sync_subscriptions_with_emby_snapshot(subscriptions: list[dict], snapshot: dict[str, list[dict[str, Any]]]) -> dict:
    counts = _episode_counts(snapshot.get("episodes", []))
    tmdb_details = await _missing_tmdb_details(subscriptions)
    updated = matched = completed_removed = 0
    now = utc_now()

    with db() as conn:
        for subscription in subscriptions:
            state = _library_state(subscription, snapshot, counts, tmdb_details.get(int(subscription["id"])))
            if state["in_library"]:
                matched += 1
            completed_removed += 1 if state["newly_completed"] else 0
            if _subscription_state_unchanged(subscription, state):
                continue
            _update_subscription_state(conn, subscription["id"], state, now)
            updated += 1

    if updated:
        add_log("info", "emby", "订阅入库状态已同步", {"updated": updated, "matched": matched, "completed": completed_removed})
    if completed_removed:
        add_log("info", "subscription", "已完整入库的订阅已停止监听并从我的订阅移除", {"count": completed_removed})
    return {"ok": True, "updated": updated, "matched": matched, "completed": completed_removed}


def _episode_counts(episodes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_series_id: dict[str, int] = {}
    by_series_name: dict[str, int] = {}
    for episode in episodes:
        series_id = str(episode.get("SeriesId") or episode.get("ParentId") or "")
        if series_id:
            by_series_id[series_id] = by_series_id.get(series_id, 0) + 1
        series_name = _compact_match_text(episode.get("SeriesName"))
        if series_name:
            by_series_name[series_name] = by_series_name.get(series_name, 0) + 1
    return {"by_series_id": by_series_id, "by_series_name": by_series_name}


async def _missing_tmdb_details(subscriptions: list[dict]) -> dict[int, dict[str, Any]]:
    details: dict[int, dict[str, Any]] = {}
    for subscription in subscriptions:
        if not _needs_tmdb_detail(subscription):
            continue
        try:
            details[int(subscription["id"])] = await TmdbAdapter().detail("tv", int(subscription["tmdb_id"]))
        except Exception as exc:
            add_log("debug", "tmdb", "同步媒体库时补全总集数失败", {"id": subscription.get("id"), "error": str(exc)})
    return details


def _needs_tmdb_detail(subscription: dict) -> bool:
    tmdb_total_count = int(subscription.get("tmdb_total_count") or 0)
    tmdb_seasons = subscription.get("tmdb_seasons") or []
    return bool(subscription.get("media_type") == "tv" and subscription.get("tmdb_id") and not (tmdb_total_count and tmdb_seasons))


def _subscription_state_unchanged(subscription: dict, state: dict[str, Any]) -> bool:
    episode_keys = [_json_episode_key(key) for key in sorted(state["owned_episodes"])]
    return (
        subscription.get("in_library") == bool(state["in_library"])
        and int(subscription.get("emby_count") or 0) == state["emby_count"]
        and int(subscription.get("tmdb_total_count") or 0) == state["tmdb_total_count"]
        and subscription.get("tmdb_seasons") == state["tmdb_seasons"]
        and subscription.get("emby_episode_keys") == episode_keys
        and subscription.get("status") == state["status"]
        and subscription.get("completed_at") == state["completed_at"]
    )


def _update_subscription_state(conn, subscription_id: int, state: dict[str, Any], now: str) -> None:
    conn.execute(
        """
        UPDATE subscriptions
        SET in_library = ?, emby_count = ?, tmdb_total_count = ?, tmdb_seasons = ?,
            emby_episode_keys = ?, status = ?, completed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            1 if state["in_library"] else 0,
            state["emby_count"],
            state["tmdb_total_count"],
            json_dumps(state["tmdb_seasons"]),
            json_dumps([_json_episode_key(key) for key in sorted(state["owned_episodes"])]),
            state["status"],
            state["completed_at"],
            now,
            subscription_id,
        ),
    )
