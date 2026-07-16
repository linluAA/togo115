from __future__ import annotations

import time
from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_UNAVAILABLE, SHARE_UNKNOWN
from app.services.subscription.search.share115_cache import process_115_cache
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
from app.services.search_metrics import record_115_validation, record_attach_outcome
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
        samples = [
            {
                "title": str(getattr(result, "title", "") or "")[:120],
                "source": str(getattr(result, "source", "") or "")[:80],
                "url": str(getattr(result, "url", "") or "")[:160],
                "message_id": getattr(result, "message_id", None),
            }
            for result in results[:3]
        ]
        add_log(
            "info",
            "subscription",
            "TG 已提取链接但标题上下文未命中订阅，已跳过以避免错误投递",
            {
                "id": subscription_id,
                "title": subscription.get("title"),
                "candidates": len(results),
                "samples": samples,
            },
        )
    # Progressive validation with duplicate fall-through:
    # order by missing-episode coverage, validate 115 one-by-one, skip expired and
    # already-saved packs, stop at the first newly created resource.
    ordered = fallback_result_candidates(raw_matched, subscription)
    matched: list[SearchResult] = []
    recheck_results: list[SearchResult] = []
    validation_started = time.perf_counter()
    validation_report: dict[str, Any] = {"checked_115": 0, "expired_115": 0, "recheck_115": 0}
    created: list[dict] = []
    duplicate_count = 0
    save_failed_count = 0
    recheck_saved_count = 0
    with db() as conn:
        existing_rows = existing_resource_rows(conn, subscription_id)
        share_cache = process_115_cache() if ordered else None
        for result in ordered:
            url = str(getattr(result, "url", "") or "")
            mark_recheck = False
            if share_cache is not None and PAN115_URL_RE.match(url):
                state = await share_cache.availability(url)
                validation_report["checked_115"] += 1
                if state == SHARE_UNAVAILABLE:
                    validation_report["expired_115"] += 1
                    add_log(
                        "info",
                        "subscription",
                        "115 分享链接已失效，跳过保存和投递",
                        {
                            "url": url,
                            "title": str(getattr(result, "title", "") or "")[:120],
                            "source": getattr(result, "source", ""),
                        },
                    )
                    continue
                if state == SHARE_UNKNOWN:
                    validation_report["recheck_115"] += 1
                    mark_recheck = True
                    recheck_results.append(result)
                    add_log(
                        "warning",
                        "subscription",
                        "115 分享链接有效性待复检，先继续投递",
                        {
                            "url": url,
                            "title": str(getattr(result, "title", "") or "")[:120],
                            "source": getattr(result, "source", ""),
                        },
                    )
            outcome = _save_telegram_result(
                conn,
                subscription,
                result,
                existing_rows,
                mark_recheck=mark_recheck,
            )
            if outcome == "created":
                matched = [result]
                created.append(getattr(result, "_saved_item"))
                if mark_recheck:
                    recheck_saved_count += 1
                break
            if outcome == "duplicate":
                duplicate_count += 1
                continue
            save_failed_count += 1
        if not created:
            for result in recheck_results:
                outcome = _save_telegram_result(conn, subscription, result, existing_rows, mark_recheck=True)
                if outcome == "created":
                    matched = [result]
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
    validation_report = {**validation_report, "115_ms": int((time.perf_counter() - validation_started) * 1000)}

    log_unmatched_results(facade, subscription, results, matched, source_label="TG 历史搜索")
    summary = {
        "raw_matched": len(raw_matched),
        "available_matched": len(matched),
        "created": len(created),
        "duplicates": duplicate_count,
        "save_failed": save_failed_count,
        "recheck_saved": recheck_saved_count,
        "from_index": any(
            str(getattr(result, "source", "") or "") == "TelegramIndex"
            or str(getattr(result, "source", "") or "").startswith("TelegramIndex:")
            for result in results
        ),
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
    record_115_validation(
        {
            "id": subscription_id,
            "115_ms": summary.get("115_ms", 0),
            "checked_115": summary.get("checked_115", 0),
            "expired_115": summary.get("expired_115", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "created": summary.get("created", 0),
            "from_index": summary.get("from_index", False),
        }
    )
    record_attach_outcome(
        {
            "id": subscription_id,
            "created": summary.get("created", 0),
            "duplicates": summary.get("duplicates", 0),
            "expired_115": summary.get("expired_115", 0),
            "save_failed": summary.get("save_failed", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "raw_matched": summary.get("raw_matched", 0),
            "candidates": len(results),
            "from_index": summary.get("from_index", False),
        }
    )
    if results and not created:
        add_log(
            "info",
            "subscription",
            "TG 提取结果未形成新投递",
            {
                "id": subscription_id,
                "title": subscription.get("title"),
                "candidates": len(results),
                "raw_matched": summary.get("raw_matched", 0),
                "available_matched": summary.get("available_matched", 0),
                "created": summary.get("created", 0),
                "duplicates": summary.get("duplicates", 0),
                "expired_115": summary.get("expired_115", 0),
                "recheck_115": summary.get("recheck_115", 0),
                "save_failed": summary.get("save_failed", 0),
                "from_index": summary.get("from_index", False),
                "samples": [
                    {
                        "title": str(getattr(result, "title", "") or "")[:120],
                        "source": str(getattr(result, "source", "") or "")[:80],
                        "url": str(getattr(result, "url", "") or "")[:160],
                    }
                    for result in results[:3]
                ],
            },
        )
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
