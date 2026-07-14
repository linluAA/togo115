from __future__ import annotations

import sqlite3
from importlib import import_module

from app.db import add_log, db, json_dumps, utc_now
from app.schemas import SubscriptionCreate
from app.services.subscription.crud.duplicates import _duplicate_subscription
from app.services.subscription.crud.rows import get_subscription
from app.services.subscription.library.sync import sync_subscription_list_with_emby
from app.services.subscription.match.matching import _normalize_quality_rules, _subscription_release_year


async def create_subscription(payload: SubscriptionCreate) -> dict:
    existing = _duplicate_subscription(payload)
    if existing:
        add_log("info", "subscription", "订阅已存在，跳过重复创建", {"id": existing.get("id"), "title": existing.get("title")})
        return existing

    subscription_id = _insert_subscription_payload(payload)
    await _sync_created_subscription_with_emby(subscription_id)
    add_log("info", "subscription", "创建订阅，历史消息搜索已进入后台", {"title": payload.title})
    _schedule_subscription_search(subscription_id)
    return get_subscription(subscription_id) or {}


def _insert_subscription_payload(payload: SubscriptionCreate) -> int:
    now = utc_now()
    values = _create_subscription_values(payload, now)
    with db() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                (title, media_type, tmdb_id, poster_url, overview, release_year, keywords, quality_rules, delivery_mode, target_path,
                 tmdb_total_count, tmdb_seasons, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        except sqlite3.IntegrityError:
            existing = _duplicate_subscription(payload)
            if existing:
                return int(existing["id"])
            raise
        return int(cursor.lastrowid)


def _create_subscription_values(payload: SubscriptionCreate, now: str) -> tuple:
    keywords = payload.keywords or [payload.title]
    release_year = payload.release_year or _subscription_release_year({"title": payload.title})
    return (
        payload.title,
        payload.media_type,
        payload.tmdb_id,
        payload.poster_url,
        payload.overview,
        release_year,
        json_dumps(keywords),
        json_dumps(_normalize_quality_rules(payload.quality_rules)),
        payload.delivery_mode,
        payload.target_path,
        int(payload.tmdb_total_count or 0),
        json_dumps([]),
        now,
        now,
    )


async def _sync_created_subscription_with_emby(subscription_id: int) -> None:
    subscription = get_subscription(subscription_id)
    if not subscription:
        return
    try:
        await sync_subscription_list_with_emby([subscription])
    except Exception as exc:
        add_log("warning", "emby", "创建订阅后同步 Emby 已有集数失败", {"id": subscription_id, "error": str(exc)})


def _schedule_subscription_search(subscription_id: int) -> None:
    schedule_subscription_search = import_module("app.services.subscription.search.tasks").schedule_subscription_search
    schedule_subscription_search(subscription_id)
