from __future__ import annotations

from app.db import add_log, db, json_dumps, utc_now
from app.services.adapters.media import EmbyAdapter, TmdbAdapter
from app.services.subscription_health import _enrich_subscriptions_with_health
from app.services.subscription_library_match import (
    _emby_configured,
    _emby_item_matches,
    _episodes_for_subscription,
    _mark_completed_subscription,
    _subscription_should_hide,
    result_matches_missing_episodes,
)
from app.services.subscription_library_snapshot import EMBY_SNAPSHOT_FAILED, EMBY_SYNC_TIMEOUT_SECONDS, _library_snapshot_or_none
from app.services.subscription_library_sync import sync_subscription_list_with_emby, sync_subscriptions_with_emby_snapshot
from app.services.subscription_matching import _json_episode_key, _subscription_release_year, _tmdb_seasons_from_detail


async def enrich_subscription_with_library(subscription: dict, snapshot: dict[str, list[dict]] | None = None) -> dict:
    subscription = await _enrich_subscription_with_tmdb(subscription)
    if not _emby_configured():
        return subscription
    if snapshot is EMBY_SNAPSHOT_FAILED or (snapshot is not None and "__failed__" in snapshot):
        return {**subscription, "emby_snapshot_failed": True}
    try:
        snapshot = snapshot if snapshot is not None else await EmbyAdapter().library_snapshot()
    except Exception as exc:
        add_log("warning", "emby", "缺集过滤获取 Emby 快照失败，已跳过本轮推送", {"id": subscription.get("id"), "error": str(exc)})
        return {**subscription, "emby_snapshot_failed": True}

    if subscription.get("media_type") == "movie":
        match = next((item for item in snapshot.get("movies", []) if _emby_item_matches(subscription, item)), None)
        return {**subscription, "in_library": bool(match), "emby_count": 1 if match else 0}
    return _enrich_tv_subscription_with_library(subscription, snapshot)


async def _enrich_subscription_with_tmdb(subscription: dict) -> dict:
    if not _needs_tmdb_enrichment(subscription):
        return subscription
    try:
        detail = await TmdbAdapter().detail(subscription.get("media_type") or "tv", int(subscription["tmdb_id"]))
    except Exception as exc:
        add_log("debug", "tmdb", "订阅总集数补全失败", {"id": subscription.get("id"), "error": str(exc)})
        return subscription

    total = int(detail.get("number_of_episodes") or 0)
    tmdb_seasons = _tmdb_seasons_from_detail(detail) if subscription.get("media_type") == "tv" else []
    release_year = _release_year_from_detail(detail, subscription)
    if not (total or tmdb_seasons or release_year):
        return subscription

    with db() as conn:
        conn.execute(
            "UPDATE subscriptions SET tmdb_total_count = ?, tmdb_seasons = ?, release_year = ?, updated_at = ? WHERE id = ?",
            (total, json_dumps(tmdb_seasons), release_year, utc_now(), subscription["id"]),
        )
    return {**subscription, "tmdb_total_count": total, "tmdb_seasons": tmdb_seasons, "release_year": release_year}


def _needs_tmdb_enrichment(subscription: dict) -> bool:
    return bool(
        subscription.get("tmdb_id")
        and (
            not int(subscription.get("tmdb_total_count") or 0)
            or (subscription.get("media_type") == "tv" and not subscription.get("tmdb_seasons"))
            or not _subscription_release_year(subscription)
        )
    )


def _release_year_from_detail(detail: dict, subscription: dict) -> int | None:
    release_year_text = str(detail.get("first_air_date") or detail.get("release_date") or "")[:4]
    return int(release_year_text) if release_year_text.isdigit() else _subscription_release_year(subscription)


def _enrich_tv_subscription_with_library(subscription: dict, snapshot: dict[str, list[dict]]) -> dict:
    series = snapshot.get("series", [])
    episodes = snapshot.get("episodes", [])
    match = next((item for item in series if _emby_item_matches(subscription, item)), None)
    series_id = str(match.get("Id") or "") if match else ""
    owned_episodes = _episodes_for_subscription(subscription, episodes, series_id)
    enriched = {**subscription, "emby_episodes": owned_episodes, "emby_episode_keys": [_json_episode_key(key) for key in sorted(owned_episodes)]}
    if owned_episodes and len(owned_episodes) != int(subscription.get("emby_count") or 0):
        enriched["emby_count"] = len(owned_episodes)
    return enriched
