from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.matching import result_debug_payload
from app.services.subscription.resource.ops import (
    existing_resource_rows,
    fallback_blocked_by_primary_resource,
    fallback_result_candidates,
    insert_resource_safely,
    matching_results,
    subscription_115_resources,
)


def match_fallback_groups(
    facade: Any,
    subscription: dict,
    groups: list[dict[str, Any]],
) -> tuple[int, list[tuple[dict[str, Any], list[SearchResult], list[SearchResult]]]]:
    total = 0
    matched_groups: list[tuple[dict[str, Any], list[SearchResult], list[SearchResult]]] = []
    for group in groups:
        group_results = list(group.get("results") or [])
        total += len(group_results)
        matched_groups.append((group, group_results, matching_results(subscription, group_results)))
    return total, matched_groups


def attach_first_fallback_result(
    facade: Any,
    subscription: dict,
    group_matches: list[tuple[dict[str, Any], list[SearchResult], list[SearchResult]]],
    excluded_urls: set[str] | None = None,
) -> list[dict]:
    subscription_id = int(subscription["id"])
    created: list[dict] = []
    for group, _, matched_results in group_matches:
        selected_result = _attach_first_from_group(subscription, matched_results, excluded_urls or set())
        if not selected_result:
            if matched_results:
                _log_unattached_fallback(subscription_id, group, matched_results)
            continue
        created.append(selected_result["item"])
        _log_selected_fallback(subscription_id, group, matched_results, selected_result["result"])
        break
    return created


async def attach_fallback_results_until_delivered(
    facade: Any,
    subscription: dict,
    group_matches: list[tuple[dict[str, Any], list[SearchResult], list[SearchResult]]],
    deliver: Callable[[int], Awaitable[bool]],
) -> list[dict]:
    subscription_id = int(subscription["id"])
    created: list[dict] = []
    attempted_urls: set[str] = set()
    for group, _, matched_results in group_matches:
        while True:
            selected_result = _attach_first_from_group(subscription, matched_results, attempted_urls)
            if not selected_result:
                if matched_results:
                    _log_unattached_fallback(subscription_id, group, matched_results)
                break
            item = selected_result["item"]
            result = selected_result["result"]
            created.append(item)
            attempted_urls.add(str(result.url or ""))
            _log_selected_fallback(subscription_id, group, matched_results, result)
            if await _deliver_fallback_candidate(subscription_id, item, result, deliver):
                if len(created) > 1:
                    add_log(
                        "info",
                        "delivery",
                        "磁力候选重试成功，已停止继续尝试",
                        {"id": subscription_id, "resource_id": item["resource_id"], "attempts": len(created), "title": result.title},
                    )
                return created
            add_log(
                "warning",
                "delivery",
                "磁力投递失败，自动尝试下一候选",
                {"id": subscription_id, "resource_id": item["resource_id"], "attempts": len(created), "title": result.title, "url": result.url},
            )
    return created


async def _deliver_fallback_candidate(
    subscription_id: int,
    item: dict[str, Any],
    result: SearchResult,
    deliver: Callable[[int], Awaitable[bool]],
) -> bool:
    try:
        ok = bool(await deliver(int(item["resource_id"])))
        if not ok:
            _mark_candidate_delivery_failed_if_pending(int(item["resource_id"]))
        return ok
    except Exception as exc:
        _mark_candidate_delivery_failed_if_pending(int(item["resource_id"]), str(exc))
        add_log(
            "error",
            "delivery",
            "磁力候选投递任务异常，自动尝试下一候选",
            {"id": subscription_id, "resource_id": item["resource_id"], "title": result.title, "url": result.url, "error": str(exc), "error_type": type(exc).__name__},
        )
        return False


def _mark_candidate_delivery_failed_if_pending(resource_id: int, error: str | None = None) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = 'skipped',
                last_error = COALESCE(?, last_error, '磁力投递失败，自动尝试下一候选'),
                updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (error, utc_now(), resource_id),
        )


def _attach_first_from_group(
    subscription: dict,
    matched_results: list[SearchResult],
    excluded_urls: set[str] | None = None,
) -> dict[str, Any] | None:
    subscription_id = int(subscription["id"])
    excluded = excluded_urls or set()
    with db() as conn:
        existing_rows = existing_resource_rows(conn, subscription_id)
        existing_115 = subscription_115_resources(conn, subscription_id)
        for candidate in fallback_result_candidates(matched_results, subscription):
            if str(candidate.url or "") in excluded:
                continue
            if _fallback_candidate_blocked(conn, subscription, candidate, existing_115):
                continue
            item = insert_resource_safely(conn, subscription, candidate, existing_rows)
            if not item:
                continue
            conn.execute(
                "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
                (utc_now(), utc_now(), subscription_id),
            )
            return {"item": item, "result": candidate}
    return None


def _fallback_candidate_blocked(conn, subscription: dict, candidate: SearchResult, existing_115: list[dict[str, Any]]) -> bool:
    subscription_id = int(subscription["id"])
    try:
        fallback_blocked = fallback_blocked_by_primary_resource(conn, subscription, candidate, existing_115)
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "订阅源/磁力阻断判断异常，已跳过单条结果",
            {"id": subscription_id, **result_debug_payload(candidate), "error": str(exc)},
        )
        return True
    if fallback_blocked:
        add_log("debug", "subscription", "已有 115 资源，跳过订阅源/磁力结果", {"id": subscription_id, "title": candidate.title})
    return fallback_blocked


def _log_selected_fallback(subscription_id: int, group: dict[str, Any], matched_results: list[SearchResult], selected_result: SearchResult) -> None:
    source = group.get("source") or {}
    add_log(
        "info",
        "subscription",
        "高优先级订阅源已命中，已选择可用结果并停止继续搜索",
        {
            "id": subscription_id,
            "source": source.get("name"),
            "priority": group.get("priority"),
            "matches": len(matched_results),
            "selected": selected_result.title,
        },
    )


def _log_unattached_fallback(subscription_id: int, group: dict[str, Any], matched_results: list[SearchResult]) -> None:
    source = group.get("source") or {}
    add_log(
        "warning",
        "subscription",
        "订阅源结果已匹配但没有保存成功，已继续尝试下一来源",
        {
            "id": subscription_id,
            "source": source.get("name"),
            "priority": group.get("priority"),
            "matches": len(matched_results),
            "samples": [result_debug_payload(result) for result in matched_results[:3]],
        },
    )
