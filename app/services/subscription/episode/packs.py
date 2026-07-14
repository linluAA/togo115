from __future__ import annotations

from app.services.subscription.episode.explicit import _episode_counts_from_pack_text, _season_numbers_from_text, episodes_from_text
from app.services.subscription.episode.keys import _all_tmdb_episode_keys, _expand_episode_range, missing_episode_keys
from app.services.subscription.episode.patterns import FULL_SERIES_PACK_RE, FULL_SERIES_WIDE_PACK_RE, PLAIN_EPISODE_RANGE_RE, SEASON_PACK_WORD_RE


def _episode_keys_by_season(keys: set[tuple[int, int]]) -> dict[int, set[tuple[int, int]]]:
    grouped: dict[int, set[tuple[int, int]]] = {}
    for season, episode in keys:
        grouped.setdefault(season, set()).add((season, episode))
    return grouped


def _season_keys_for_counts(subscription: dict, counts: set[int], missing: set[tuple[int, int]]) -> set[tuple[int, int]]:
    if not counts:
        return set()
    expected_by_season = _episode_keys_by_season(_all_tmdb_episode_keys(subscription))
    if not expected_by_season:
        return set()
    total_expected = set().union(*expected_by_season.values()) if expected_by_season else set()
    if sum(len(keys) for keys in expected_by_season.values()) in counts:
        return total_expected
    missing_by_season = _episode_keys_by_season(missing)
    for count in sorted(counts, reverse=True):
        inferred = _season_keys_for_count(expected_by_season, missing_by_season, count)
        if inferred:
            return inferred
    if len(expected_by_season) == 1:
        return set(expected_by_season[next(iter(expected_by_season))])
    return set()


def _season_keys_for_count(
    expected_by_season: dict[int, set[tuple[int, int]]],
    missing_by_season: dict[int, set[tuple[int, int]]],
    count: int,
) -> set[tuple[int, int]]:
    seasons_with_missing = [season for season, keys in expected_by_season.items() if len(keys) == count and missing_by_season.get(season)]
    if len(seasons_with_missing) == 1:
        return set(expected_by_season[seasons_with_missing[0]])
    seasons_with_count = [season for season, keys in expected_by_season.items() if len(keys) == count]
    if len(seasons_with_count) == 1:
        return set(expected_by_season[seasons_with_count[0]])
    return set()


def _pack_episode_keys_from_text(subscription: dict, text: str | None) -> set[tuple[int, int]]:
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return set()
    value = text or ""
    explicit_episodes = episodes_from_text(value)
    seasons = _season_numbers_from_text(value)
    inferred = _pack_keys_with_season_context(subscription, value, seasons, explicit_episodes)
    if seasons:
        return inferred & expected
    if explicit_episodes:
        return set()
    if FULL_SERIES_WIDE_PACK_RE.search(value) or FULL_SERIES_PACK_RE.search(value):
        return set(expected)
    return _season_keys_for_counts(subscription, _episode_counts_from_pack_text(value), missing_episode_keys(subscription)) & expected


def _pack_keys_with_season_context(
    subscription: dict,
    text: str,
    seasons: set[int],
    explicit_episodes: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    if not seasons:
        return set()
    expected_by_season = _episode_keys_by_season(_all_tmdb_episode_keys(subscription))
    inferred: set[tuple[int, int]] = set()
    for season in seasons:
        if SEASON_PACK_WORD_RE.search(text) and not explicit_episodes and season in expected_by_season:
            inferred.update(expected_by_season[season])
    if len(seasons) == 1:
        season = next(iter(seasons))
        inferred.update(_season_range_keys(text, season))
        inferred.update(_season_count_keys(text, season, expected_by_season))
    return inferred


def _season_range_keys(text: str, season: int) -> set[tuple[int, int]]:
    keys: set[tuple[int, int]] = set()
    for match in PLAIN_EPISODE_RANGE_RE.finditer(text):
        start = int(match.group("start"))
        end = int(match.group("end"))
        keys.update(_expand_episode_range(season, start, end))
    return keys


def _season_count_keys(text: str, season: int, expected_by_season: dict[int, set[tuple[int, int]]]) -> set[tuple[int, int]]:
    counts = _episode_counts_from_pack_text(text)
    if not counts or season not in expected_by_season:
        return set()
    season_expected = expected_by_season[season]
    if len(season_expected) in counts or SEASON_PACK_WORD_RE.search(text):
        return set(season_expected)
    return _expand_episode_range(season, 1, max(counts))


def episode_keys_from_text_for_subscription(subscription: dict | None, text: str | None) -> set[tuple[int, int]]:
    episodes = episodes_from_text(text or "")
    if subscription:
        seasons = _season_numbers_from_text(text)
        if len(seasons) == 1:
            season = next(iter(seasons))
            if season != 1:
                episodes = {(season, episode) if item_season == 1 else (item_season, episode) for item_season, episode in episodes}
        episodes.update(_pack_episode_keys_from_text(subscription, text))
    return episodes
