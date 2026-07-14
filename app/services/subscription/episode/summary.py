from __future__ import annotations

from collections.abc import Iterable

from app.services.subscription.episode.parser import _all_tmdb_episode_keys, _episode_keys_from_json, _missing_episode_keys


def episode_range_labels(keys: Iterable[tuple[int, int]], *, limit: int = 8) -> list[str]:
    grouped: dict[int, list[int]] = {}
    for season, episode in sorted(set(keys)):
        grouped.setdefault(season, []).append(episode)
    labels: list[str] = []
    for season, episodes in grouped.items():
        start = previous = None
        for episode in episodes:
            if start is None:
                start = previous = episode
                continue
            if previous is not None and episode == previous + 1:
                previous = episode
                continue
            labels.append(_range_label(season, start, previous))
            start = previous = episode
        if start is not None:
            labels.append(_range_label(season, start, previous))
    if len(labels) > limit:
        return [*labels[:limit], f"+{len(labels) - limit}"]
    return labels


def subscription_episode_snapshot(subscription: dict) -> dict:
    if subscription.get("media_type") != "tv":
        return {}
    expected = _all_tmdb_episode_keys(subscription)
    missing = _missing_episode_keys(subscription)
    owned = subscription.get("emby_episodes")
    if not isinstance(owned, set):
        owned = _episode_keys_from_json(subscription.get("emby_episode_keys"))
    return {
        "expected_count": len(expected),
        "owned_count": len(owned) or int(subscription.get("emby_count") or 0),
        "missing_count": len(missing),
        "missing_ranges": episode_range_labels(missing),
    }


def _range_label(season: int, start: int, end: int | None) -> str:
    end = end or start
    if start == end:
        return f"S{season:02d}E{start:02d}"
    return f"S{season:02d}E{start:02d}-E{end:02d}"
