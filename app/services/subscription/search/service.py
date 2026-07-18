from __future__ import annotations

import asyncio
from typing import Any

from app.db import add_log, db, utc_now
from app.services.subscription.crud.service import get_subscription
from app.services.subscription.delivery.service import deliver_resource
from app.services.subscription.episode.summary import subscription_episode_snapshot
from app.services.subscription.library.service import mark_completed_subscription, subscription_should_hide, enrich_subscription_with_library
from app.services.subscription.search.flow import _search_fallback_when_needed, _search_telegram_first, _telegram_should_skip_fallback


async def search_and_attach_resources(
    subscription_id: int,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
    *,
    incremental_telegram: bool = False,
) -> list[dict]:
    subscription = get_subscription(subscription_id)
    if not subscription or subscription.get("status") != "active":
        return []

    subscription = await enrich_subscription_with_library(subscription, snapshot)
    _log_subscription_episode_snapshot(subscription)
    if subscription_should_hide(subscription):
        mark_completed_subscription(subscription)
        add_log(
            "info",
            "subscription",
            "订阅已完整入库，跳过搜索并停止监听",
            {"id": subscription_id, "title": subscription.get("title")},
        )
        return []

    created, telegram_matches, telegram_summary = await _search_telegram_first(subscription, incremental_telegram)
    if created:
        if await _deliver_created_resources(created):
            return created
        add_log(
            "warning",
            "subscription",
            "TG 资源已保存但投递失败，继续搜索订阅源/磁力兜底",
            {"id": subscription_id, "count": len(created)},
        )
    if not created and telegram_matches and _telegram_should_skip_fallback(telegram_summary, subscription):
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
                (utc_now(), utc_now(), subscription_id),
            )
        return []

    fallback_created = await _search_fallback_when_needed(subscription, deliver_func=deliver_resource)
    if fallback_created:
        created.extend(fallback_created)

    with db() as conn:
        conn.execute(
            "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription_id),
        )
    return created


def _log_subscription_episode_snapshot(subscription: dict) -> None:
    episode_snapshot = subscription_episode_snapshot(subscription)
    if not episode_snapshot:
        return
    add_log(
        "debug",
        "subscription",
        "\u8ba2\u9605\u7f3a\u96c6\u5feb\u7167",
        {
            "id": subscription.get("id"),
            "title": subscription.get("title"),
            "emby_snapshot_failed": bool(subscription.get("emby_snapshot_failed")),
            **episode_snapshot,
        },
    )


async def _deliver_created_resources(created: list[dict]) -> bool:
    results = await asyncio.gather(
        *(_deliver_created_resource(item["resource_id"]) for item in created),
        return_exceptions=True,
    )
    return all(result is True for result in results)


async def _deliver_created_resource(resource_id: int) -> bool:
    try:
        ok = await deliver_resource(resource_id)
        if not ok:
            _mark_resource_failed_if_pending(resource_id, "资源投递失败，继续搜索兜底资源")
        return ok
    except Exception as exc:
        add_log(
            "error",
            "delivery",
            "资源后台投递任务异常，已保留资源记录",
            {"resource_id": resource_id, "error": str(exc), "error_type": type(exc).__name__},
        )
        _mark_resource_failed_if_pending(resource_id, str(exc))
        return False


def _mark_resource_failed_if_pending(resource_id: int, error: str) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = 'failed',
                last_error = COALESCE(last_error, ?),
                updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (error[:500], utc_now(), resource_id),
        )


from app.services.subscription.attach.service import attach_results_to_matching_subscriptions, refresh_rss_sources
from app.services.subscription.search.all import search_all_active_subscriptions
