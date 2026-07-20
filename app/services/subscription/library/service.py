from __future__ import annotations

import time
from app.db import add_log, db, json_dumps, utc_now
from app.services.adapters.media import EmbyAdapter, TmdbAdapter
from app.services.subscription.library.health import enrich_subscriptions_with_health
from app.services.subscription.library.match import (
    _emby_configured,
    _emby_item_matches,
    _episodes_for_subscription,
    mark_completed_subscription,
    subscription_should_hide,
    result_matches_missing_episodes,
)
from app.services.subscription.library.snapshot import EMBY_SNAPSHOT_FAILED, EMBY_SYNC_TIMEOUT_SECONDS, library_snapshot_or_none
from app.services.subscription.library.sync import sync_subscription_list_with_emby, sync_subscriptions_with_emby_snapshot
from app.services.subscription.match.matching import json_episode_key, subscription_release_year, tmdb_seasons_from_detail


_TMDB_REFRESH_MEMO: dict[int, float] = {}
_TMDB_REFRESH_COOLDOWN_SECONDS = 6 * 3600


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
    tmdb_seasons = tmdb_seasons_from_detail(detail) if subscription.get("media_type") == "tv" else []
    release_year = _release_year_from_detail(detail, subscription)
    if not (total or tmdb_seasons or release_year):
        return subscription

    with db() as conn:
        conn.execute(
            "UPDATE subscriptions SET tmdb_total_count = ?, tmdb_seasons = ?, release_year = ?, updated_at = ? WHERE id = ?",
            (total, json_dumps(tmdb_seasons), release_year, utc_now(), subscription["id"]),
        )
    try:
        sid = int(subscription.get("id") or 0)
        if sid:
            _TMDB_REFRESH_MEMO[sid] = time.time()
    except (TypeError, ValueError):
        pass
    return {**subscription, "tmdb_total_count": total, "tmdb_seasons": tmdb_seasons, "release_year": release_year}


def _needs_tmdb_enrichment(subscription: dict) -> bool:
    if not subscription.get("tmdb_id"):
        return False
    total = int(subscription.get("tmdb_total_count") or 0)
    seasons = subscription.get("tmdb_seasons") or []
    if not total:
        return True
    if subscription.get("media_type") == "tv" and not seasons:
        return True
    if not subscription_release_year(subscription):
        return True
    if subscription.get("media_type") != "tv":
        return False
    if str(subscription.get("status") or "").casefold() == "completed":
        return False

    emby_count = int(subscription.get("emby_count") or 0)
    # Library caught up with last known TMDB total: airing shows often gain new episodes later.
    if total > 0 and emby_count >= total:
        return _tmdb_refresh_due(subscription)

    # Active and currently "no missing" under cached map — revalidate before skip-search.
    if str(subscription.get("status") or "active").casefold() == "active":
        try:
            from app.services.subscription.episode.parser import missing_episode_keys

            if not missing_episode_keys(subscription):
                return _tmdb_refresh_due(subscription)
        except Exception:
            return _tmdb_refresh_due(subscription)
    return False


def _tmdb_refresh_due(subscription: dict) -> bool:
    try:
        sid = int(subscription.get("id") or 0)
    except (TypeError, ValueError):
        sid = 0
    if not sid:
        return True
    last = _TMDB_REFRESH_MEMO.get(sid, 0.0)
    return (time.time() - last) >= _TMDB_REFRESH_COOLDOWN_SECONDS




async def prefetch_tmdb_for_subscriptions(subscriptions: list[dict], *, limit: int = 20) -> int:
    """Refresh a bounded set of stale TV TMDB maps before bulk search.

    Returns number of successful refreshes. Failures are ignored so search can continue.
    """
    import asyncio

    candidates = [item for item in subscriptions if _needs_tmdb_enrichment(item)]
    if not candidates:
        return 0
    # Prefer higher urgency ids first while keeping bounded external calls.
    candidates = candidates[: max(1, min(int(limit or 20), 40))]
    semaphore = asyncio.Semaphore(3)
    refreshed = 0

    async def one(item: dict) -> None:
        nonlocal refreshed
        async with semaphore:
            before_total = int(item.get("tmdb_total_count") or 0)
            updated = await _enrich_subscription_with_tmdb(item)
            if int(updated.get("tmdb_total_count") or 0) != before_total or updated.get("tmdb_seasons") != item.get("tmdb_seasons"):
                refreshed += 1
            # Mutate original dict so later waves see fresher map without re-read.
            item.update({
                "tmdb_total_count": updated.get("tmdb_total_count", item.get("tmdb_total_count")),
                "tmdb_seasons": updated.get("tmdb_seasons", item.get("tmdb_seasons")),
                "release_year": updated.get("release_year", item.get("release_year")),
            })

    await asyncio.gather(*(one(item) for item in candidates), return_exceptions=True)
    if refreshed:
        add_log("debug", "tmdb", "搜索前批量刷新 TMDB 季表完成", {"candidates": len(candidates), "refreshed": refreshed})
    return refreshed


def _release_year_from_detail(detail: dict, subscription: dict) -> int | None:
    release_year_text = str(detail.get("first_air_date") or detail.get("release_date") or "")[:4]
    return int(release_year_text) if release_year_text.isdigit() else subscription_release_year(subscription)


def _enrich_tv_subscription_with_library(subscription: dict, snapshot: dict[str, list[dict]]) -> dict:
    series = snapshot.get("series", [])
    episodes = snapshot.get("episodes", [])
    match = next((item for item in series if _emby_item_matches(subscription, item)), None)
    series_id = str(match.get("Id") or "") if match else ""
    owned_episodes = _episodes_for_subscription(subscription, episodes, series_id)
    enriched = {**subscription, "emby_episodes": owned_episodes, "emby_episode_keys": [json_episode_key(key) for key in sorted(owned_episodes)]}
    if owned_episodes and len(owned_episodes) != int(subscription.get("emby_count") or 0):
        enriched["emby_count"] = len(owned_episodes)
    return enriched
