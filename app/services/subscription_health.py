from __future__ import annotations

from typing import Any

from app.db import db
from app.services.subscription_episode_keys import _missing_episode_keys
from app.services.subscription_library_match import _subscription_is_complete


def _episode_range_summary(keys: set[tuple[int, int]], limit: int = 4) -> str:
    if not keys:
        return ""
    ranges: list[str] = []
    for season in sorted({season for season, _ in keys}):
        episodes = sorted(episode for item_season, episode in keys if item_season == season)
        start = previous = episodes[0]
        season_ranges: list[str] = []
        for episode in episodes[1:]:
            if episode == previous + 1:
                previous = episode
                continue
            season_ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
            start = previous = episode
        season_ranges.append(f"{start}" if start == previous else f"{start}-{previous}")
        prefix = f"S{season:02d}E"
        ranges.extend(f"{prefix}{part}" for part in season_ranges)
    if len(ranges) > limit:
        return "、".join(ranges[:limit]) + f" 等 {len(keys)} 集"
    return "、".join(ranges)


def _subscription_health_from_stats(subscription: dict, stats: dict[str, Any]) -> dict[str, Any]:
    missing = _missing_episode_keys(subscription)
    latest_status = stats.get("latest_resource_status") or ""
    failed_count = int(stats.get("failed_resources") or 0)
    if subscription.get("status") == "completed" or _subscription_is_complete(subscription):
        state = "ok"
        label = "订阅完成"
        detail = "媒体库已完整入库"
    elif failed_count:
        state = "danger"
        label = "投递异常"
        detail = f"{failed_count} 条资源投递失败"
    elif not subscription.get("last_checked_at"):
        state = "idle"
        label = "等待搜索"
        detail = "还没有完成首次历史搜索"
    elif subscription.get("media_type") == "tv" and missing:
        state = "ok"
        label = "追新中"
        detail = f"缺失 {len(missing)} 集：{_episode_range_summary(missing)}"
    else:
        state = "ok"
        label = "运行正常"
        detail = "最近搜索正常"
    return {
        "state": state,
        "label": label,
        "detail": detail,
        "last_checked_at": subscription.get("last_checked_at"),
        "latest_resource_status": latest_status,
        "failed_resources": failed_count,
        "missing_episode_count": len(missing),
        "missing_episode_summary": _episode_range_summary(missing),
    }


def _enrich_subscriptions_with_health(subscriptions: list[dict]) -> list[dict]:
    if not subscriptions:
        return subscriptions
    ids = [int(item["id"]) for item in subscriptions if item.get("id")]
    placeholders = ",".join("?" for _ in ids)
    stats: dict[int, dict[str, Any]] = {subscription_id: {} for subscription_id in ids}
    if not ids:
        return subscriptions
    with db() as conn:
        for row in conn.execute(
            f"""
            SELECT subscription_id,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_resources
            FROM resources
            WHERE subscription_id IN ({placeholders})
            GROUP BY subscription_id
            """,
            ids,
        ).fetchall():
            stats[int(row["subscription_id"])]["failed_resources"] = int(row["failed_resources"] or 0)
        for row in conn.execute(
            f"""
            SELECT r.subscription_id, r.status AS latest_resource_status
            FROM resources r
            JOIN (
                SELECT subscription_id, MAX(id) AS id
                FROM resources
                WHERE subscription_id IN ({placeholders})
                GROUP BY subscription_id
            ) latest ON latest.id = r.id
            """,
            ids,
        ).fetchall():
            stats[int(row["subscription_id"])]["latest_resource_status"] = row["latest_resource_status"]
    for subscription in subscriptions:
        subscription["health"] = _subscription_health_from_stats(subscription, stats.get(int(subscription.get("id") or 0), {}))
    return subscriptions




