from __future__ import annotations

from typing import Any

from app.db import utc_now
from app.services.subscription.library.match import (
    _emby_item_matches,
    _emby_names,
    _episodes_for_subscription,
    _subscription_is_complete,
)
from app.services.subscription.match.matching import compact_match_text, tmdb_seasons_from_detail


def _library_state(
    subscription: dict,
    snapshot: dict[str, list[dict[str, Any]]],
    counts: dict[str, dict[str, int]],
    tmdb_detail: dict[str, Any] | None,
) -> dict[str, Any]:
    tmdb_total_count, tmdb_seasons = _tmdb_metadata(subscription, tmdb_detail)
    if subscription["media_type"] == "movie":
        match = next((item for item in snapshot.get("movies", []) if _emby_item_matches(subscription, item)), None)
        owned_episodes: set[tuple[int, int]] = set()
        emby_count = 1 if match else 0
        in_library = bool(match)
    else:
        match = next((item for item in snapshot.get("series", []) if _emby_item_matches(subscription, item)), None)
        series_id = str(match.get("Id") or "") if match else ""
        owned_episodes = _episodes_for_subscription(subscription, snapshot.get("episodes", []), series_id)
        emby_count = _series_episode_count(subscription, match, series_id, owned_episodes, counts)
        in_library = bool(match or emby_count)

    status, completed_at, completed = _completion_state(subscription, tmdb_total_count, tmdb_seasons, owned_episodes, emby_count, in_library)
    return {
        "in_library": in_library,
        "emby_count": emby_count,
        "tmdb_total_count": tmdb_total_count,
        "tmdb_seasons": tmdb_seasons,
        "owned_episodes": owned_episodes,
        "status": status,
        "completed_at": completed_at,
        "newly_completed": completed and subscription.get("status") != "completed",
    }


def _tmdb_metadata(subscription: dict, tmdb_detail: dict[str, Any] | None) -> tuple[int, list[dict[str, Any]]]:
    tmdb_total_count = int(subscription.get("tmdb_total_count") or 0)
    tmdb_seasons = subscription.get("tmdb_seasons") or []
    if tmdb_detail:
        tmdb_total_count = tmdb_total_count or int(tmdb_detail.get("number_of_episodes") or 0)
        tmdb_seasons = tmdb_seasons_from_detail(tmdb_detail)
    return tmdb_total_count, tmdb_seasons


def _completion_state(
    subscription: dict,
    tmdb_total_count: int,
    tmdb_seasons: list[dict[str, Any]],
    owned_episodes: set[tuple[int, int]],
    emby_count: int,
    in_library: bool,
) -> tuple[str, str | None, bool]:
    enriched = {
        **subscription,
        "tmdb_total_count": tmdb_total_count,
        "tmdb_seasons": tmdb_seasons,
        "emby_episodes": owned_episodes,
        "emby_count": emby_count,
        "in_library": in_library,
    }
    completed = _subscription_is_complete(enriched, in_library, emby_count)
    status = "completed" if completed or subscription.get("status") == "completed" else subscription.get("status", "active")
    completed_at = subscription.get("completed_at")
    if status == "completed" and not completed_at:
        completed_at = utc_now()
    if status != "completed":
        completed_at = None
    return status, completed_at, status == "completed"


def _series_episode_count(
    subscription: dict,
    match: dict[str, Any] | None,
    series_id: str,
    owned_episodes: set[tuple[int, int]],
    counts: dict[str, dict[str, int]],
) -> int:
    count = len(owned_episodes) or counts["by_series_id"].get(series_id, 0)
    if match and not count:
        for name in _emby_names(match):
            count = counts["by_series_name"].get(compact_match_text(name), 0)
            if count:
                return count
    if not match and not count:
        count = _series_episode_count_by_name(subscription, counts["by_series_name"])
    return count


def _series_episode_count_by_name(subscription: dict, episode_count_by_series_name: dict[str, int]) -> int:
    subscription_title = compact_match_text(subscription.get("title"))
    for series_name, count in episode_count_by_series_name.items():
        if series_name == subscription_title:
            return count
        if len(subscription_title) >= 4 and subscription_title in series_name:
            return count
        if len(series_name) >= 4 and series_name in subscription_title:
            return count
    return 0
