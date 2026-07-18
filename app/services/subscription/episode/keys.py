from __future__ import annotations

import re
from typing import Any

from app.db import json_loads


def _episode_key(season: int | None, episode: int | None) -> tuple[int, int] | None:
    if episode is None or episode <= 0:
        return None
    return (season or 1, episode)


def _episode_key_from_item(item: dict) -> tuple[int, int] | None:
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    try:
        season_number = int(season) if season is not None else 1
        episode_number = int(episode) if episode is not None else None
    except (TypeError, ValueError):
        return None
    return _episode_key(season_number, episode_number)


def _expand_episode_range(season: int | None, start: int, end: int | None = None) -> set[tuple[int, int]]:
    if start <= 0:
        return set()
    end = end or start
    if end < start or end - start > 120:
        return set()
    return {((season or 1), episode) for episode in range(start, end + 1)}


def json_episode_key(key: tuple[int, int]) -> str:
    return f"{key[0]}x{key[1]}"


def _episode_key_from_json(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return _episode_key(int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
        if match:
            return _episode_key(int(match.group(1)), int(match.group(2)))
    return None


def _episode_keys_from_json(value: Any) -> set[tuple[int, int]]:
    if isinstance(value, str):
        value = json_loads(value, [])
    if not isinstance(value, list):
        return set()
    keys = {_episode_key_from_json(item) for item in value}
    return {key for key in keys if key}


def tmdb_seasons_from_detail(detail: dict) -> list[dict[str, int]]:
    seasons: list[dict[str, int]] = []
    for season in detail.get("seasons") or []:
        try:
            season_number = int(season.get("season_number"))
            episode_count = int(season.get("episode_count") or 0)
        except (TypeError, ValueError):
            continue
        if season_number <= 0 or episode_count <= 0:
            continue
        seasons.append({"season_number": season_number, "episode_count": episode_count})
    return seasons


def _all_tmdb_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    seasons = subscription.get("tmdb_seasons")
    if isinstance(seasons, str):
        seasons = json_loads(seasons, [])
    keys: set[tuple[int, int]] = set()
    if isinstance(seasons, list):
        for season in seasons:
            if not isinstance(season, dict):
                continue
            try:
                season_number = int(season.get("season_number"))
                episode_count = int(season.get("episode_count") or 0)
            except (TypeError, ValueError):
                continue
            if season_number <= 0 or episode_count <= 0:
                continue
            keys.update((season_number, episode) for episode in range(1, episode_count + 1))
    if keys:
        return keys
    total = int(subscription.get("tmdb_total_count") or 0)
    return {(1, episode) for episode in range(1, total + 1)} if total > 0 else set()


def owned_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    """Return owned episode keys for a TV subscription.

    Prefer explicit Emby episode keys. Only fall back to continuous S01
    ownership from ``emby_count`` when the expected scope is pure S01 (or
    has no multi-season map). Multi-season shows without keys return empty
    ownership so missing-episode logic stays conservative.
    """
    owned = subscription.get("emby_episodes")
    if not isinstance(owned, set):
        owned = _episode_keys_from_json(subscription.get("emby_episode_keys"))
    if owned:
        return owned
    try:
        count = int(subscription.get("emby_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return set()
    expected = _all_tmdb_episode_keys(subscription)
    if expected and not all(season == 1 for season, _ in expected):
        return set()
    return {(1, episode) for episode in range(1, count + 1)}


def missing_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    if subscription.get("media_type") != "tv":
        return set()
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return set()
    return expected - owned_episode_keys(subscription)


