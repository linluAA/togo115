from __future__ import annotations

from app.db import db, json_loads, row_to_dict, utc_now
from app.services.subscription.library.service import _enrich_subscriptions_with_health, _subscription_should_hide
from app.services.subscription.match.matching import _normalize_quality_rules, _subscription_release_year


def normalize_subscription(row) -> dict:
    item = row_to_dict(row) or {}
    item["keywords"] = json_loads(item.get("keywords"), [])
    item["quality_rules"] = _normalize_quality_rules(json_loads(item.get("quality_rules"), {}))
    item["in_library"] = bool(item.get("in_library"))
    item["tmdb_seasons"] = json_loads(item.get("tmdb_seasons"), [])
    item["emby_episode_keys"] = json_loads(item.get("emby_episode_keys"), [])
    if item.get("release_year") is None:
        item["release_year"] = _subscription_release_year(item)
    return item


def list_subscriptions(include_completed: bool = False) -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    subscriptions = [normalize_subscription(row) for row in rows]
    if not include_completed:
        subscriptions = [item for item in subscriptions if not _subscription_should_hide(item)]
    return _enrich_subscriptions_with_health(subscriptions)


def get_subscription(subscription_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    return normalize_subscription(row) if row else None


def _active_subscriptions() -> list[dict]:
    return [item for item in list_subscriptions() if item.get("status") == "active"]


def _mark_subscription_checked(subscription_id: int) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute("UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?", (now, now, subscription_id))
