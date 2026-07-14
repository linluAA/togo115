from __future__ import annotations

from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.delivery.link_validation import classify_115_results
from app.services.subscription.resource.ops import (
    _existing_resource_rows,
    _fallback_result_candidates,
    _insert_resource_safely,
    _matching_results,
    _resource_already_exists,
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
    raw_matched = _matching_results(subscription, results)
    if not raw_matched and results:
        add_log(
            "info",
            "subscription",
            "TG 已提取链接但标题上下文未命中订阅，已跳过以避免错误投递",
            {"id": subscription_id, "title": subscription.get("title"), "candidates": len(results)},
        )
    matched, recheck_results, validation_report = await classify_115_results(raw_matched)
    created: list[dict] = []
    duplicate_count = 0
    save_failed_count = 0
    recheck_saved_count = 0
    with db() as conn:
        existing_rows = _existing_resource_rows(conn, subscription_id)
        for result in _fallback_result_candidates(matched, subscription):
            outcome = _save_telegram_result(conn, subscription, result, existing_rows, mark_recheck=False)
            if outcome == "created":
                created.append(getattr(result, "_saved_item"))
                break
            if outcome == "duplicate":
                duplicate_count += 1
            else:
                save_failed_count += 1
        if not created:
            for result in _fallback_result_candidates(recheck_results, subscription):
                outcome = _save_telegram_result(conn, subscription, result, existing_rows, mark_recheck=True)
                if outcome == "created":
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
    _log_telegram_attach_summary(subscription_id, summary)
    return created, matched, summary


def _save_telegram_result(conn, subscription: dict, result: SearchResult, existing_rows: list[dict[str, Any]], *, mark_recheck: bool) -> str:
    subscription_id = int(subscription["id"])
    duplicate_reason = _resource_already_exists(conn, subscription_id, result, subscription, existing_rows)
    if duplicate_reason:
        add_log(
            "debug",
            "subscription",
            "TG 资源已存在，跳过重复保存",
            {"id": subscription_id, "url": result.url, "title": result.title, "reason": duplicate_reason},
        )
        return "duplicate"
    item = _insert_resource_safely(conn, subscription, result, existing_rows)
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
