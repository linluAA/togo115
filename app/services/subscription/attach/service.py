from __future__ import annotations

from typing import Any

from app.db import add_log, db
from app.services.adapters.pan115 import PAN115_URL_RE, Pan115Adapter
from app.services.adapters.telegram import TelegramBotAdapter
from app.services.integration_state import get_setting
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.subscription.attach.match import _fallback_is_blocked, _result_matches_subscription
from app.services.subscription.attach.queries import _active_subscription_queries
from app.services.subscription.crud.service import _active_subscriptions, get_subscription
from app.services.subscription.delivery.service import deliver_resource as _deliver_resource_impl
from app.services.subscription.library.service import (
    _library_snapshot_or_none,
    _mark_completed_subscription,
    _subscription_should_hide,
    enrich_subscription_with_library,
    sync_subscriptions_with_emby_snapshot,
)
from app.services.subscription.delivery.link_validation import filter_available_115_results
from app.services.subscription.match.matching import (
    _result_is_fallback_source,
    _result_priority,
)
from app.services.subscription.resource.ops import (
    _existing_resource_rows,
    _insert_resource_safely,
    _results_may_match_subscription,
    _subscription_115_resources,
)


async def attach_results_to_matching_subscriptions(
    results: list[SearchResult],
    message_text: str,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    subscriptions = _active_subscriptions()
    if snapshot is None:
        snapshot = await _library_snapshot_or_none()
    if snapshot is not None and "__failed__" not in snapshot:
        await sync_subscriptions_with_emby_snapshot(subscriptions, snapshot)
        subscriptions = _active_subscriptions()

    attached = 0
    resource_ids: list[int] = []
    ordered_results = sorted(
        results,
        key=lambda result: (-_result_priority(result), str(getattr(result, "source", "")), str(getattr(result, "message_id", ""))),
    )
    ordered_results = await filter_available_115_results(ordered_results)
    for subscription in subscriptions:
        if not _results_may_match_subscription(subscription, ordered_results, message_text):
            continue
        subscription = get_subscription(subscription["id"]) or subscription
        if subscription.get("status") != "active":
            continue
        subscription = await enrich_subscription_with_library(subscription, snapshot)
        if _subscription_should_hide(subscription):
            _mark_completed_subscription(subscription)
            add_log("info", "subscription", "订阅已完整入库，跳过实时资源并停止监听", {"id": subscription.get("id"), "title": subscription.get("title")})
            continue
        attached += _attach_results_for_subscription(subscription, ordered_results, resource_ids)

    for resource_id in resource_ids:
        await _deliver_resource(resource_id)
    if attached:
        add_log("info", "subscription", "实时监控发现并处理新资源", {"count": attached})
    return attached


def _attach_results_for_subscription(subscription: dict, ordered_results: list[SearchResult], resource_ids: list[int]) -> int:
    attached = 0
    fallback_matched_priority: int | None = None
    fallback_attached = False
    with db() as conn:
        existing_rows = _existing_resource_rows(conn, int(subscription["id"]))
        existing_115 = _subscription_115_resources(conn, int(subscription["id"]))
        for result in ordered_results:
            is_fallback = _result_is_fallback_source(result)
            if is_fallback and fallback_attached:
                continue
            if is_fallback and fallback_matched_priority is not None and _result_priority(result) < fallback_matched_priority:
                continue
            if not _result_matches_subscription(subscription, result):
                continue
            if _fallback_is_blocked(conn, subscription, result, existing_115):
                if is_fallback and fallback_matched_priority is None:
                    fallback_matched_priority = _result_priority(result)
                continue
            item = _insert_resource_safely(conn, subscription, result, existing_rows)
            if item and PAN115_URL_RE.match(str(getattr(result, "url", "") or "")):
                existing_115.insert(0, {"title": result.title, "url": result.url, "status": "pending"})
            if is_fallback and fallback_matched_priority is None:
                fallback_matched_priority = _result_priority(result)
            if not item:
                continue
            attached += 1
            resource_ids.append(item["resource_id"])
            if is_fallback:
                fallback_attached = True
    return attached


async def _deliver_resource(resource_id: int) -> bool:
    return await _deliver_resource_impl(
        resource_id,
        get_setting_func=get_setting,
        pan115_adapter_cls=Pan115Adapter,
        telegram_bot_adapter_cls=TelegramBotAdapter,
    )


async def refresh_rss_sources(snapshot: dict[str, list[dict[str, Any]]] | None = None) -> dict:
    queries = _active_subscription_queries()
    results = await RssTorznabAdapter().fetch_due_sources(queries)
    if not results:
        return {"ok": True, "results": 0, "count": 0}
    attached = await attach_results_to_matching_subscriptions(results, "", snapshot)
    return {"ok": True, "results": len(results), "count": attached}
