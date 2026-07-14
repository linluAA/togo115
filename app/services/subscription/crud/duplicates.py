from __future__ import annotations

from app.db import db
from app.schemas import SubscriptionCreate
from app.services.subscription.crud.rows import normalize_subscription
from app.services.subscription.library.service import mark_completed_subscription, subscription_should_hide
from app.services.subscription.match.matching import compact_match_text


def duplicate_subscription(payload: SubscriptionCreate) -> dict | None:
    rows = []
    with db() as conn:
        if payload.tmdb_id is not None:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id = ?",
                (payload.media_type, payload.tmdb_id),
            ).fetchone()
            if row:
                return _visible_duplicate_or_none(normalize_subscription(row))
        title = compact_match_text(payload.title)
        if title:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id IS NULL",
                (payload.media_type,),
            ).fetchall()
    for row in rows:
        item = normalize_subscription(row)
        if subscription_should_hide(item):
            mark_completed_subscription(item)
            continue
        if compact_match_text(item.get("title")) == title:
            return item
    return None


def _visible_duplicate_or_none(item: dict) -> dict | None:
    if subscription_should_hide(item):
        mark_completed_subscription(item)
        return None
    return item
