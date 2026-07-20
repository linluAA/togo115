from __future__ import annotations


from app.db import db, utc_now
from app.services.integration_state import get_setting
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.episode.parser import (
    _all_tmdb_episode_keys,
    _episode_key_from_item,
    episode_keys_from_text_for_subscription,
    missing_episode_keys,
    owned_episode_keys,
)
from app.services.subscription.match.matching import (
    compact_match_text,
    _result_is_primary_115_resource,
    result_text,
)


def _emby_provider_tmdb_id(item: dict) -> str:
    provider_ids = item.get("ProviderIds") or {}
    for key in ("Tmdb", "TMDB", "TheMovieDb"):
        value = provider_ids.get(key)
        if value:
            return str(value)
    return ""


def _emby_names(item: dict) -> list[str]:
    names = [item.get("Name"), item.get("OriginalTitle"), item.get("SortName"), item.get("SeriesName")]
    return [str(name).strip() for name in names if name]


def _emby_item_matches(subscription: dict, item: dict) -> bool:
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "")
    item_tmdb_id = _emby_provider_tmdb_id(item)
    if subscription_tmdb_id and item_tmdb_id and subscription_tmdb_id == item_tmdb_id:
        return True
    subscription_title = compact_match_text(subscription.get("title"))
    if not subscription_title:
        return False
    for name in _emby_names(item):
        item_title = compact_match_text(name)
        if item_title == subscription_title:
            return True
        if len(subscription_title) >= 4 and subscription_title in item_title:
            return True
    return False


def _episode_matches_subscription(subscription: dict, episode: dict, matched_series_id: str = "") -> bool:
    if matched_series_id and str(episode.get("SeriesId") or episode.get("ParentId") or "") == matched_series_id:
        return True
    return _emby_item_matches(subscription, episode)


def _episodes_for_subscription(subscription: dict, episodes: list[dict], matched_series_id: str = "") -> set[tuple[int, int]]:
    owned: set[tuple[int, int]] = set()
    for episode in episodes:
        if not _episode_matches_subscription(subscription, episode, matched_series_id):
            continue
        key = _episode_key_from_item(episode)
        if key:
            owned.add(key)
    return owned


def _subscription_is_complete(subscription: dict, in_library: bool | None = None, emby_count: int | None = None) -> bool:
    media_type = subscription.get("media_type")
    library = bool(subscription.get("in_library")) if in_library is None else bool(in_library)
    count = int(subscription.get("emby_count") or 0) if emby_count is None else int(emby_count or 0)
    if media_type == "movie":
        return library
    expected = _all_tmdb_episode_keys(subscription)
    if expected:
        owned = owned_episode_keys(subscription)
        if owned:
            # Explicit keys are authoritative; never complete on bare count alone.
            return expected.issubset(owned)
        # Without keys, only allow count-based completion for pure S01 expectations.
        if all(season == 1 for season, _ in expected):
            return count >= len(expected)
        return False
    total = int(subscription.get("tmdb_total_count") or 0)
    return bool(total and count >= total)


def subscription_should_hide(subscription: dict) -> bool:
    return subscription.get("status") == "completed" or _subscription_is_complete(subscription)


def mark_completed_subscription(subscription: dict) -> None:
    if subscription.get("status") == "completed":
        return
    with db() as conn:
        conn.execute(
            "UPDATE subscriptions SET status = 'completed', completed_at = COALESCE(completed_at, ?), updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription["id"]),
        )



    from app.services.subscription.crud.rows import invalidate_subscription_list_cache as _inv_sub_list
    _inv_sub_list()

def _emby_configured() -> bool:
    config = get_setting("emby")
    return bool(str(config.get("server_url") or "").strip() and str(config.get("api_key") or "").strip())



def result_matches_missing_episodes(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    # Emby snapshot failure must not freeze subscription attach/delivery.
    # Treat library state as unknown and keep searching/saving.
    if subscription.get("media_type") != "tv":
        if subscription.get("emby_snapshot_failed"):
            return True
        return not bool(subscription.get("in_library"))
    if subscription.get("emby_snapshot_failed"):
        return True
    text = result_text(result, *extra_texts)
    episodes = episode_keys_from_text_for_subscription(subscription, text)
    owned = _owned_episode_keys(subscription)
    if episodes and owned and episodes.issubset(owned):
        return False
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return not bool(episodes and owned)
    missing = missing_episode_keys(subscription)
    if not missing:
        return False
    if episodes:
        return bool(episodes & missing)
    # Bare title with no episode/pack labels: only Telegram primary 115 may pass as
    # last-resort. Haisou/site plugins must carry pack/episode markers (e.g. 全41集).
    if missing and _result_is_primary_115_resource(result):
        return True
    return False


def _owned_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    return owned_episode_keys(subscription)




