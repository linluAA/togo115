from __future__ import annotations

import asyncio
from importlib import import_module

from app.db import add_log
import app.services.subscription.runtime as runtime
from app.services.subscription.crud.service import active_subscriptions, mark_subscription_checked, get_subscription
from app.services.subscription.library.service import EMBY_SYNC_TIMEOUT_SECONDS, sync_subscriptions_with_emby_snapshot
from app.services.subscription.library.snapshot import library_snapshot_or_none


async def search_all_active_subscriptions() -> dict:
    subscriptions = active_subscriptions()
    wave_size = runtime.search_all_wave_size()
    add_log(
        "info",
        "subscription",
        "搜索全部活跃订阅开始",
        {
            "active": len(subscriptions),
            "concurrency": runtime.SUBSCRIPTION_SEARCH_CONCURRENCY,
            "wave_size": wave_size,
            "desired_concurrency": runtime.desired_search_concurrency(),
        },
    )
    snapshot = await library_snapshot_or_none()
    # Emby sync is useful, but must not block the first subscription search.
    emby_task = asyncio.create_task(_sync_emby_in_background(list(subscriptions), snapshot))
    try:
        outcomes = await _search_subscriptions_in_waves(list(subscriptions), snapshot)
    finally:
        try:
            await asyncio.wait_for(asyncio.shield(emby_task), timeout=max(1.0, EMBY_SYNC_TIMEOUT_SECONDS))
        except Exception:
            if not emby_task.done():
                emby_task.cancel()
                try:
                    await emby_task
                except Exception:
                    pass
    searched = sum(item[0] for item in outcomes)
    total = sum(item[1] for item in outcomes)
    failed = sum(item[2] for item in outcomes)
    add_log(
        "info",
        "subscription",
        "搜索全部活跃订阅完成",
        {"active": len(subscriptions), "searched": searched, "created": total, "failed": failed},
    )
    return {"ok": True, "searched": searched, "count": total, "failed": failed}


async def _search_subscriptions_in_waves(subscriptions: list[dict], snapshot) -> list[tuple[int, int, int]]:
    """Launch subscriptions in adaptive waves instead of one giant gather.

    This keeps the same total work order (stable list order) while limiting how
    many subscription searches become runnable at once under FloodWait pressure.
    """
    if not subscriptions:
        return []
    outcomes: list[tuple[int, int, int]] = []
    index = 0
    wave_no = 0
    while index < len(subscriptions):
        wave_size = max(1, runtime.search_all_wave_size())
        wave = subscriptions[index : index + wave_size]
        wave_no += 1
        add_log(
            "debug",
            "subscription",
            "搜索全部活跃订阅分波启动",
            {
                "wave": wave_no,
                "wave_size": len(wave),
                "remaining": max(0, len(subscriptions) - index - len(wave)),
                "desired_concurrency": runtime.desired_search_concurrency(),
            },
        )
        wave_outcomes = await asyncio.gather(*(_search_one(subscription, snapshot) for subscription in wave))
        outcomes.extend(wave_outcomes)
        index += len(wave)
        if index < len(subscriptions):
            stagger = float(getattr(runtime, "SEARCH_ALL_WAVE_STAGGER_SECONDS", 0.05) or 0.0)
            if stagger > 0:
                await asyncio.sleep(stagger)
    return outcomes


async def _sync_emby_in_background(subscriptions: list[dict], snapshot) -> None:
    if snapshot is None or "__failed__" in snapshot:
        return
    try:
        add_log("debug", "subscription", "搜索并行同步 Emby 入库状态开始", {"active": len(subscriptions)})
        await asyncio.wait_for(
            sync_subscriptions_with_emby_snapshot(subscriptions, snapshot),
            timeout=EMBY_SYNC_TIMEOUT_SECONDS,
        )
        add_log("debug", "subscription", "搜索并行同步 Emby 入库状态完成", {"active": len(active_subscriptions())})
    except asyncio.TimeoutError:
        add_log(
            "warning",
            "subscription",
            "搜索并行 Emby 入库状态同步超时，已跳过",
            {"timeout": EMBY_SYNC_TIMEOUT_SECONDS},
        )
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "搜索并行 Emby 入库状态同步失败，已跳过",
            {"error": str(exc)},
        )


async def _search_one(subscription: dict, snapshot) -> tuple[int, int, int]:
    await asyncio.sleep(runtime.SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS)
    subscription = get_subscription(subscription["id"]) or subscription
    if subscription.get("status") != "active":
        return (0, 0, 0)
    add_log("debug", "subscription", "开始搜索订阅", {"id": subscription.get("id"), "title": subscription.get("title")})
    try:
        results = await asyncio.wait_for(
            _search_and_attach_resources_guarded(subscription["id"], snapshot, incremental_telegram=False),
            timeout=runtime.SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        mark_subscription_checked(int(subscription["id"]))
        add_log(
            "error",
            "subscription",
            "搜索订阅超时，已继续处理下一个订阅",
            {"id": subscription["id"], "title": subscription.get("title"), "timeout": runtime.SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS},
        )
        return (1, 0, 1)
    except Exception as exc:
        mark_subscription_checked(int(subscription["id"]))
        add_log(
            "error",
            "subscription",
            "搜索订阅失败，已继续处理下一个订阅",
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
    guarded = import_module("app.services.subscription.search.tasks")._search_and_attach_resources_guarded
    return await guarded(subscription_id, snapshot, incremental_telegram=incremental_telegram)
