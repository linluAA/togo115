from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.db import add_log
import app.services.subscription.runtime as runtime
from app.services.jobs import create_job, latest_job

SearchCallable = Callable[[int, dict[str, list[dict[str, Any]]] | None], Awaitable[list[dict]]]


def _search_semaphore() -> asyncio.Semaphore:
    return runtime.search_semaphore()


async def _default_search(
    subscription_id: int,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
    *,
    incremental_telegram: bool = False,
) -> list[dict]:
    from app.services.subscription.search.service import search_and_attach_resources

    return await search_and_attach_resources(subscription_id, snapshot, incremental_telegram=incremental_telegram)


async def _default_search_all() -> dict:
    from app.services.subscription.search.all import search_all_active_subscriptions

    return await search_all_active_subscriptions()


async def _default_emby_sync() -> dict:
    from app.services.subscription.crud.service import list_subscriptions
    from app.services.subscription.library.service import sync_subscription_list_with_emby

    return await sync_subscription_list_with_emby(list_subscriptions(include_completed=True), force=True)


async def _search_and_attach_resources_guarded(
    subscription_id: int,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
    *,
    incremental_telegram: bool = False,
    search_func: Callable[..., Awaitable[list[dict]]] | None = None,
) -> list[dict]:
    """Serialize one subscription and respect process-wide search concurrency."""
    search_func = search_func or _default_search
    lock = runtime.subscription_lock(subscription_id)
    if lock.locked():
        add_log(
            "info",
            "subscription",
            '订阅搜索已在运行，已跳过重复触发',
            {"id": subscription_id, "incremental_telegram": incremental_telegram},
        )
        return []
    async with lock:
        async with runtime.search_semaphore():
            return await search_func(subscription_id, snapshot, incremental_telegram=incremental_telegram)


def _reuse_or_create_job(kind: str, target_id: int | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = latest_job(kind, target_id)
    if existing and existing.get("status") in {"queued", "running"}:
        return {
            "ok": True,
            "queued": existing.get("status") == "queued",
            "running": True,
            "job_id": existing.get("id"),
            "reused": True,
        }
    job_id = create_job(kind, target_id, payload)
    return {"ok": True, "queued": True, "running": True, "job_id": job_id, "reused": False}


def schedule_subscription_search(subscription_id: int) -> dict:
    result = _reuse_or_create_job(
        "subscription_search",
        int(subscription_id),
        {"id": int(subscription_id)},
    )
    result["id"] = int(subscription_id)
    if not result.get("reused"):
        add_log(
            "info",
            "subscription",
            '订阅搜索已加入后台队列',
            {"id": subscription_id, "job_id": result.get("job_id")},
        )
    return result


def schedule_search_all_active_subscriptions() -> dict:
    result = _reuse_or_create_job("subscription_search_all")
    if not result.get("reused"):
        add_log(
            "info",
            "subscription",
            '搜索全部活跃订阅已加入后台队列',
            {"job_id": result.get("job_id")},
        )
    return result


def schedule_emby_subscription_sync() -> dict:
    result = _reuse_or_create_job("emby_subscription_sync")
    if not result.get("reused"):
        add_log(
            "info",
            "emby",
            '手动 Emby 入库状态同步已加入后台队列',
            {"job_id": result.get("job_id")},
        )
    return result
