from __future__ import annotations

from typing import Any

from app.db import add_log, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.resource.ops import insert_resource_safely, resource_already_exists


def _save_telegram_result(conn, subscription: dict, result: SearchResult, existing_rows: list[dict[str, Any]]) -> str:
    subscription_id = int(subscription["id"])
    add_log("debug",
        "subscription",
        "TG 尝试保存资源",
        {
            "id": subscription_id,
            "url": str(getattr(result, "url", "") or "")[:160],
            "title": str(getattr(result, "title", "") or "")[:120],
            "source": str(getattr(result, "source", "") or "")[:80],
            "message_id": str(getattr(result, "message_id", "") or ""),
        },
    )
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
    return "created"

def _log_telegram_attach_summary(subscription_id: int, summary: dict[str, Any]) -> None:
    if not summary.get("raw_matched"):
        return
    if summary.get("created"):
        return
    if summary.get("duplicates") == summary.get("available_matched") and summary.get("available_matched"):
        add_log("debug", "subscription", "TG 资源已存在，本次不再重复保存", {"id": subscription_id, **summary})
        return
    if summary.get("save_failed"):
        add_log("warning", "subscription", "TG 资源匹配成功但保存失败，将继续搜索订阅源/磁力", {"id": subscription_id, **summary})