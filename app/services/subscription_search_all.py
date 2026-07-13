from __future__ import annotations

import asyncio
from importlib import import_module

from app.db import add_log
from app.services import subscription_runtime as runtime
from app.services.subscription_crud import _active_subscriptions, _mark_subscription_checked, get_subscription
from app.services.subscription_library import EMBY_SYNC_TIMEOUT_SECONDS, sync_subscriptions_with_emby_snapshot
from app.services.subscription_library_snapshot import _library_snapshot_or_none


async def search_all_active_subscriptions() -> dict:
    subscriptions = _active_subscriptions()
    add_log(
        "info",
        "subscription",
        "\u624b\u52a8\u641c\u7d22\u5168\u90e8\u8ba2\u9605\u5f00\u59cb",
        {"active": len(subscriptions), "concurrency": runtime.SUBSCRIPTION_SEARCH_CONCURRENCY},
    )
    snapshot = await _library_snapshot_or_none()
    subscriptions = await _sync_emby_before_search(subscriptions, snapshot)
    outcomes = await asyncio.gather(*(_search_one(subscription, snapshot) for subscription in subscriptions))
    searched = sum(item[0] for item in outcomes)
    total = sum(item[1] for item in outcomes)
    failed = sum(item[2] for item in outcomes)
    add_log(
        "info",
        "subscription",
        "\u624b\u52a8\u641c\u7d22\u5168\u90e8\u8ba2\u9605\u5b8c\u6210",
        {"active": len(subscriptions), "searched": searched, "created": total, "failed": failed},
    )
    return {"ok": True, "searched": searched, "count": total, "failed": failed}


async def _sync_emby_before_search(subscriptions: list[dict], snapshot) -> list[dict]:
    if snapshot is None or "__failed__" in snapshot:
        return subscriptions
    try:
        add_log("debug", "subscription", "\u641c\u7d22\u524d\u5f00\u59cb\u540c\u6b65 Emby \u5165\u5e93\u72b6\u6001", {"active": len(subscriptions)})
        await asyncio.wait_for(sync_subscriptions_with_emby_snapshot(subscriptions, snapshot), timeout=EMBY_SYNC_TIMEOUT_SECONDS)
        subscriptions = _active_subscriptions()
        add_log("debug", "subscription", "\u641c\u7d22\u524d Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u5b8c\u6210", {"active": len(subscriptions)})
    except asyncio.TimeoutError:
        add_log("warning", "subscription", "\u641c\u7d22\u524d Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u8d85\u65f6\uff0c\u8df3\u8fc7\u540c\u6b65\u7ee7\u7eed\u641c\u7d22", {"timeout": EMBY_SYNC_TIMEOUT_SECONDS})
    except Exception as exc:
        add_log("warning", "subscription", "\u641c\u7d22\u524d Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u5931\u8d25\uff0c\u8df3\u8fc7\u540c\u6b65\u7ee7\u7eed\u641c\u7d22", {"error": str(exc)})
    return subscriptions


async def _search_one(subscription: dict, snapshot) -> tuple[int, int, int]:
    await asyncio.sleep(runtime.SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS)
    subscription = get_subscription(subscription["id"]) or subscription
    if subscription.get("status") != "active":
        return (0, 0, 0)
    add_log("debug", "subscription", "\u5f00\u59cb\u641c\u7d22\u8ba2\u9605", {"id": subscription.get("id"), "title": subscription.get("title")})
    try:
        results = await asyncio.wait_for(
            _search_and_attach_resources_guarded(subscription["id"], snapshot, incremental_telegram=False),
            timeout=runtime.SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        _mark_subscription_checked(int(subscription["id"]))
        add_log(
            "error",
            "subscription",
            "\u641c\u7d22\u8ba2\u9605\u8d85\u65f6\uff0c\u5df2\u7ee7\u7eed\u5904\u7406\u4e0b\u4e00\u4e2a\u8ba2\u9605",
            {"id": subscription["id"], "title": subscription.get("title"), "timeout": runtime.SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS},
        )
        return (1, 0, 1)
    except Exception as exc:
        _mark_subscription_checked(int(subscription["id"]))
        add_log(
            "error",
            "subscription",
            "\u641c\u7d22\u8ba2\u9605\u5931\u8d25\uff0c\u5df2\u7ee7\u7eed\u5904\u7406\u4e0b\u4e00\u4e2a\u8ba2\u9605",
            {
                "id": subscription["id"],
                "title": subscription.get("title"),
                "error": str(exc),
                "error_type": type(exc).__name__,
                "error_repr": repr(exc),
            },
        )
        return (1, 0, 1)
    return (1, len(results), 0)


async def _search_and_attach_resources_guarded(subscription_id: int, snapshot, *, incremental_telegram: bool = False):
    guarded = import_module("app.services.subscription_tasks")._search_and_attach_resources_guarded
    return await guarded(subscription_id, snapshot, incremental_telegram=incremental_telegram)
