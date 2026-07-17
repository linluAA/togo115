from __future__ import annotations

from typing import Any

from app.db import add_log, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.resource.ops import insert_resource_safely, resource_already_exists


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
