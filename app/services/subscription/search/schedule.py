from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.subscription.episode.parser import missing_episode_keys

# Skip empty re-checks inside search-all to cut wasted external I/O.
SEARCH_ALL_RECENT_CHECK_COOLDOWN_SECONDS = 600


def prioritize_subscriptions_for_search(subscriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order active subscriptions so high-yield work runs first.

    Priority:
    1) more missing TV episodes first
    2) movies not in library before library hits
    3) older last_checked_at first
    4) stable id
    """
    return sorted(subscriptions, key=_subscription_search_sort_key)


def filter_subscriptions_for_search_all(subscriptions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop recently-checked complete subscriptions from bulk search-all."""
    kept: list[dict[str, Any]] = []
    skipped = 0
    for item in subscriptions:
        if should_skip_recent_complete_check(item):
            skipped += 1
            continue
        kept.append(item)
    return prioritize_subscriptions_for_search(kept), skipped


def should_skip_recent_complete_check(subscription: dict[str, Any]) -> bool:
    age = _seconds_since_last_checked(subscription.get("last_checked_at"))
    if age is None or age >= SEARCH_ALL_RECENT_CHECK_COOLDOWN_SECONDS:
        return False
    media = str(subscription.get("media_type") or "").casefold()
    if media == "movie":
        return bool(subscription.get("in_library"))
    if media != "tv":
        return False
    # Only skip when TMDB scope is known and nothing is missing.
    total = int(subscription.get("tmdb_total_count") or 0)
    seasons = subscription.get("tmdb_seasons") or []
    if not (total or seasons):
        return False
    try:
        return not bool(missing_episode_keys(subscription))
    except Exception:
        return False


def _subscription_search_sort_key(subscription: dict[str, Any]) -> tuple[Any, ...]:
    media = str(subscription.get("media_type") or "").casefold()
    if media == "tv":
        try:
            missing = len(missing_episode_keys(subscription))
        except Exception:
            missing = 1
        urgency = missing
    elif media == "movie":
        urgency = 0 if subscription.get("in_library") else 10_000
    else:
        urgency = 1
    last_checked = str(subscription.get("last_checked_at") or "")
    # Empty last_checked sorts first among same urgency.
    try:
        sid = int(subscription.get("id") or 0)
    except (TypeError, ValueError):
        sid = 0
    return (-int(urgency), last_checked or "", sid)


def _seconds_since_last_checked(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0.0, (now - stamp.astimezone(timezone.utc)).total_seconds())
