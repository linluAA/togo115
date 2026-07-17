from __future__ import annotations

import time

from app.db import db, json_loads, row_to_dict, utc_now
from app.services.subscription.library.service import enrich_subscriptions_with_health, subscription_should_hide
from app.services.subscription.match.matching import normalize_quality_rules, subscription_release_year

SUBSCRIPTION_LIST_CACHE_TTL = 6.0
_subscription_list_cache: dict[bool, tuple[float, list[dict]]] = {}


def normalize_subscription(row) -> dict:
    item = row_to_dict(row) or {}
    item["keywords"] = json_loads(item.get("keywords"), [])
    item["quality_rules"] = normalize_quality_rules(json_loads(item.get("quality_rules"), {}))
    item["in_library"] = bool(item.get("in_library"))
    item["tmdb_seasons"] = json_loads(item.get("tmdb_seasons"), [])
    item["emby_episode_keys"] = json_loads(item.get("emby_episode_keys"), [])
    if item.get("release_year") is None:
        item["release_year"] = subscription_release_year(item)
    return item


def list_subscriptions(include_completed: bool = False) -> list[dict]:
    flag = bool(include_completed)
    cached = _subscription_list_cache.get(flag)
    if cached is not None:
        expires_at, payload = cached
        if expires_at > time.monotonic():
            return [dict(item) for item in payload]
        _subscription_list_cache.pop(flag, None)
    with db() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    subscriptions = [normalize_subscription(row) for row in rows]
    if not include_completed:
        subscriptions = [item for item in subscriptions if not subscription_should_hide(item)]
    result = enrich_subscriptions_with_health(subscriptions)
    _subscription_list_cache[flag] = (
        time.monotonic() + SUBSCRIPTION_LIST_CACHE_TTL,
        [dict(item) for item in result],
    )
    return result


def invalidate_subscription_list_cache() -> None:
    _subscription_list_cache.clear()


def get_subscription(subscription_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    return normalize_subscription(row) if row else None


def active_subscriptions() -> list[dict]:
    return [item for item in list_subscriptions() if item.get("status") == "active"]


def mark_subscription_checked(subscription_id: int) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute("UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?", (now, now, subscription_id))
