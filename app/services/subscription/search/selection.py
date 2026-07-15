from __future__ import annotations

import time
from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.delivery.link_validation import classify_115_results, pick_first_available_115_result
from app.services.subscription.resource.ops import (
    existing_resource_rows,
    fallback_result_candidates,
    insert_resource_safely,
    matching_results,
    resource_already_exists,
)
from app.services.subscription.search.selection_fallback import (
    attach_fallback_results_until_delivered,
    attach_first_fallback_result,
    match_fallback_groups,
)
from app.services.subscription.search.selection_logs import (
    log_unmatched_fallback_groups,
    log_unmatched_results,
)


async def attach_telegram_results(
    facade,
    subscription: dict,
    results: list[SearchResult],
) -> tuple[list[dict], list[SearchResult], dict[str, Any]]:
    subscription_id = int(subscription["id"])
    raw_matched = matching_results(subscription, results)
    if not raw_matched and results:
        add_log(
            "info",
            "subscription",
            "TG 已提取链接但标题上下文未命中订阅，已跳过以避免错误投递",
            {"id": subscription_id, "title": subscription.get("title"), "candidates": len(results)},
        )
    # Progressive validation: check candidates in priority order and stop at first usable link.
    ordered = fallback_result_candidates(raw_matched, subscription)
    matched: list[SearchResult] = []
    recheck_results: list[SearchResult] = []
    first_is_recheck = False
    validation_started = time.perf_counter()
    if ordered:
        first, recheck_results, validation_report, first_is_recheck = await pick_first_available_115_result(ordered)
        if first is not None:
            matched = [first]
    else:
        validation_report = {"checked_115": 0, "expired_115": 0, "recheck_115": 0}
    validation_report = {**validation_report, "115_ms": int((time.perf_counter() - validation_started) * 1000)}
    created: list[dict] = []
    duplicate_count = 0
    save_failed_count = 0
    recheck_saved_count = 0
    with db() as conn:
        existing_rows = existing_resource_rows(conn, subscription_id)
        for result in matched:
            outcome = _save_telegram_result(
                conn,
                subscription,
                result,
                existing_rows,
                mark_recheck=first_is_recheck,
            )
            if outcome == "created":
                created.append(getattr(result, "_saved_item"))
                if first_is_recheck:
                    recheck_saved_count += 1
                break
            if outcome == "duplicate":
                duplicate_count += 1
            else:
                save_failed_count += 1
        if not created:
            for result in recheck_results:
                outcome = _save_telegram_result(conn, subscription, result, existing_rows, mark_recheck=True)
                if outcome == "created":
                    created.append(getattr(result, "_saved_item"))
                    recheck_saved_count += 1
                    break
                if outcome == "duplicate":
                    duplicate_count += 1
                else:
                    save_failed_count += 1
        conn.execute(
            "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription_id),
        )
    log_unmatched_results(facade, subscription, results, matched, source_label="TG 历史搜索")
    summary = {
        "raw_matched": len(raw_matched),
        "available_matched": len(matched),
        "created": len(created),
        "duplicates": duplicate_count,
        "save_failed": save_failed_count,
        "recheck_saved": recheck_saved_count,
        "from_index": any(getattr(result, "source", "") == "TelegramIndex" for result in results),
        **validation_report,
    }
    add_log(
        "info",
        "subscription",
        "TG 搜索指标",
        {
            "id": subscription_id,
            "115_ms": summary.get("115_ms", 0),
            "checked_115": summary.get("checked_115", 0),
            "expired_115": summary.get("expired_115", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "raw_matched": summary.get("raw_matched", 0),
            "created": summary.get("created", 0),
            "from_index": summary.get("from_index", False),
        },
    )
    _log_telegram_attach_summary(subscription_id, summary)
    return created, matched, summary


def _save_telegram_result(conn, subscription: dict, result: SearchResult, existing_rows: list[dict[str, Any]], *, mark_recheck: bool) -> str:
    subscription_id = int(subscription["id"])
    duplicate_reason = resource_already_exists(conn, subscription_id, result, subscription, existing_rows)
    if duplicate_reason:
        add_log(
            "debug",
            "subscription",
            "TG 资源已存在，跳过重复保存",
            {"id": subscription_id, "url": result.url, "title": result.title, "reason": duplicate_reason},
        )
        return "duplicate"
    item = insert_resource_safely(conn, subscription, result, existing_rows)
    if not item:
        return "failed"
    setattr(result, "_saved_item", item)
    if mark_recheck:
        conn.execute(
            """
            UPDATE resources
            SET status = 'pending_recheck',
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("115 分享有效性待复检，等待重试", utc_now(), item["resource_id"]),
        )
    return "created"


def _log_telegram_attach_summary(subscription_id: int, summary: dict[str, Any]) -> None:
    if not summary.get("raw_matched"):
        return
    if summary.get("created"):
        return
    if summary.get("recheck_115") and not summary.get("available_matched"):
        add_log("warning", "subscription", "TG 命中的 115 资源需要待复检，将继续搜索订阅源/磁力", {"id": subscription_id, **summary})
        return
    if summary.get("expired_115") and not summary.get("available_matched"):
        add_log("info", "subscription", "TG 命中的 115 资源均已失效，将继续搜索订阅源/磁力", {"id": subscription_id, **summary})
        return
    if summary.get("duplicates") == summary.get("available_matched") and summary.get("available_matched"):
        add_log("info", "subscription", "TG 资源已存在，本次不再重复保存", {"id": subscription_id, **summary})
        return
    if summary.get("save_failed"):
        add_log("warning", "subscription", "TG 资源匹配成功但保存失败，将继续搜索订阅源/磁力", {"id": subscription_id, **summary})


__all__ = [
    "attach_fallback_results_until_delivered",
    "attach_first_fallback_result",
    "attach_telegram_results",
    "log_unmatched_fallback_groups",
    "log_unmatched_results",
    "match_fallback_groups",
]
