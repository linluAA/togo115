from __future__ import annotations

from typing import Callable

from app.db import add_log, db, row_to_dict, utc_now
from app.services.adapters.pan115 import PAN115_URL_RE, Pan115Adapter
from app.services.adapters.telegram import TelegramBotAdapter
from app.services.integration_state import get_setting
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.crud.service import get_subscription
from app.services.subscription.delivery.executor import _deliver_resource_url
from app.services.subscription.delivery.state import (
    _delivery_lock,
    _existing_effective_delivery,
    _load_resource_for_delivery,
    _mark_resource_duplicate_delivered,
    _update_resource_delivery_status,
)
from app.services.subscription.resource.guard import SKIP_REASONS, resource_allowed_for_subscription
from app.services.subscription.resource.resources import resource_dedupe_key


def list_failed_resources(limit: int = 100) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title, s.poster_url AS subscription_poster_url
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            WHERE r.status IN ('failed', 'delivery_failed_retryable', 'delivery_failed_final')
            ORDER BY r.updated_at DESC, r.id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 100), 500)),),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


async def retry_failed_resources(limit: int, deliver: Callable[[int], Any]) -> dict:
    failed = list_failed_resources(limit)
    ok = 0
    failed_count = 0
    for item in failed:
        if await deliver(int(item["id"])):
            ok += 1
        else:
            failed_count += 1
    return {"ok": True, "retried": len(failed), "delivered": ok, "failed": failed_count}


async def deliver_resource(
    resource_id: int,
    *,
    get_setting_func: Callable[..., dict] = get_setting,
    pan115_adapter_cls: type | None = None,
    telegram_bot_adapter_cls: type | None = None,
) -> bool:
    resource = _load_resource_for_delivery(resource_id)
    if not resource:
        return False
    dedupe_key = resource_dedupe_key(resource["url"] or "")
    if not dedupe_key:
        return await _deliver_resource_locked(resource_id, get_setting_func, pan115_adapter_cls, telegram_bot_adapter_cls)
    async with _delivery_lock(dedupe_key):
        return await _deliver_resource_locked(resource_id, get_setting_func, pan115_adapter_cls, telegram_bot_adapter_cls)


async def _deliver_resource_locked(
    resource_id: int,
    get_setting_func: Callable[..., dict],
    pan115_adapter_cls: type | None,
    telegram_bot_adapter_cls: type | None,
) -> bool:
    resource = _load_resource_for_delivery(resource_id)
    if not resource:
        return False
    if str(resource["status"] or "").casefold() == "delivered":
        return True
    if _mark_unneeded_resource_skipped(resource_id, resource):
        return False
    if _mark_existing_duplicate_if_any(resource_id, resource):
        return True

    delivery_mode, pan115_adapter_cls, telegram_bot_adapter_cls = _delivery_dependencies(
        get_setting_func,
        pan115_adapter_cls,
        telegram_bot_adapter_cls,
    )
    ok, error_message = await _perform_delivery(resource_id, resource, delivery_mode, pan115_adapter_cls, telegram_bot_adapter_cls)
    _update_resource_delivery_status(resource_id, ok, error_message)
    if not ok:
        resource_type = _resource_type_label(resource["url"] or "")
        add_log(
            "warning",
            "delivery",
            f"{resource_type}资源投递失败",
            {"resource_id": resource_id, "mode": delivery_mode, "resource_type": resource_type, "url": resource["url"] or "", "error": error_message},
        )
    return ok


def _mark_unneeded_resource_skipped(resource_id: int, resource) -> bool:
    subscription = get_subscription(int(resource["subscription_id"]))
    result = SearchResult(
        title=str(resource["title"] or ""),
        url=str(resource["url"] or ""),
        source=str(resource["source"] or ""),
        message_id=str(resource["message_id"] or "") or None,
        context=str(resource["title"] or ""),
    )
    if resource_allowed_for_subscription(subscription, result, scope="deliver", reject_reasons=SKIP_REASONS):
        return False
    with db() as conn:
        conn.execute(
            """
            UPDATE resources
            SET status = 'skipped',
                last_error = ?,
                updated_at = ?
            WHERE id = ? AND status != 'delivered'
            """,
            ("资源不在订阅缺失范围内，已跳过投递", utc_now(), resource_id),
        )
    return True


def _mark_existing_duplicate_if_any(resource_id: int, resource) -> bool:
    existing = _existing_effective_delivery(resource)
    if not existing:
        return False
    add_log(
        "info",
        "delivery",
        "资源链接已投递过，跳过重复推送",
        {
            "resource_id": resource_id,
            "existing_resource_id": existing.get("id"),
            "url": resource["url"] or "",
        },
    )
    _mark_resource_duplicate_delivered(resource_id, existing)
    return True



def _resource_type_label(url: str) -> str:
    key = resource_dedupe_key(url)
    if key and key[0] == "magnet":
        return "磁力"
    if PAN115_URL_RE.match(str(url or "")):
        return "115"
    return "下载链接"


def _delivery_dependencies(
    get_setting_func: Callable[..., dict],
    pan115_adapter_cls: type | None,
    telegram_bot_adapter_cls: type | None,
) -> tuple[str, type, type]:
    delivery = get_setting_func("delivery", {"mode": "115"})
    delivery_mode = delivery.get("mode") or "115"
    return delivery_mode, pan115_adapter_cls or Pan115Adapter, telegram_bot_adapter_cls or TelegramBotAdapter


async def _perform_delivery(
    resource_id: int,
    resource,
    delivery_mode: str,
    pan115_adapter_cls: type,
    telegram_bot_adapter_cls: type,
) -> tuple[bool, str]:
    try:
        return await _deliver_resource_url(resource, delivery_mode, pan115_adapter_cls, telegram_bot_adapter_cls)
    except Exception as exc:
        add_log(
            "error",
            "delivery",
            "资源投递失败，已记录错误",
            {"resource_id": resource_id, "mode": delivery_mode, "url": resource["url"] or "", "error": str(exc)},
        )
        return False, str(exc)
