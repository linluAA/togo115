from __future__ import annotations

from app.db import db
from app.schemas import SubscriptionCreate
from app.services.subscription_crud_rows import normalize_subscription
from app.services.subscription_library import _mark_completed_subscription, _subscription_should_hide
from app.services.subscription_matching import _compact_match_text


def _duplicate_subscription(payload: SubscriptionCreate) -> dict | None:
    rows = []
    with db() as conn:
        if payload.tmdb_id is not None:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id = ?",
                (payload.media_type, payload.tmdb_id),
            ).fetchone()
            if row:
                return _visible_duplicate_or_none(normalize_subscription(row))
        title = _compact_match_text(payload.title)
        if title:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id IS NULL",
                (payload.media_type,),
            ).fetchall()
    for row in rows:
        item = normalize_subscription(row)
        if _subscription_should_hide(item):
            _mark_completed_subscription(item)
            continue
        if _compact_match_text(item.get("title")) == title:
            return item
    return None


def _visible_duplicate_or_none(item: dict) -> dict | None:
    if _subscription_should_hide(item):
        _mark_completed_subscription(item)
        return None
    return item
