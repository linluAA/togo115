from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.db import add_log
import app.services.subscription.runtime as runtime
from app.services.subscription.crud.service import mark_subscription_checked

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
    search_func = search_func or _default_search
    lock = runtime.subscription_lock(subscription_id)
    if lock.locked():
        add_log(
            "info",
            "subscription",
            "\u8ba2\u9605\u641c\u7d22\u5df2\u5728\u8fd0\u884c\uff0c\u5df2\u8df3\u8fc7\u91cd\u590d\u89e6\u53d1",
            {"id": subscription_id, "incremental_telegram": incremental_telegram},
        )
        return []
    async with lock:
        async with runtime.search_semaphore():
            return await search_func(subscription_id, snapshot, incremental_telegram=incremental_telegram)


async def _search_subscription_background(
    subscription_id: int,
    *,
    search_func: Callable[..., Awaitable[list[dict]]] | None = None,
) -> None:
    try:
        await _search_and_attach_resources_guarded(subscription_id, search_func=search_func)
    except Exception as exc:
        mark_subscription_checked(subscription_id)
        add_log("error", "subscription", "\u8ba2\u9605\u540e\u53f0\u641c\u7d22\u5931\u8d25", {"id": subscription_id, "error": str(exc)})


async def _search_subscription_background_worker(
    subscription_id: int,
    *,
    search_func: Callable[..., Awaitable[list[dict]]] | None = None,
) -> None:
    await _search_subscription_background(subscription_id, search_func=search_func)


def schedule_subscription_search(subscription_id: int) -> dict:
    task = runtime.subscription_search_tasks.get(subscription_id)
    if task and not task.done():
        return {"ok": True, "queued": False, "running": True, "id": subscription_id}
    task = asyncio.create_task(_search_subscription_in_worker_thread(subscription_id))
    runtime.subscription_search_tasks[subscription_id] = task
    task.add_done_callback(lambda _: runtime.subscription_search_tasks.pop(subscription_id, None))
    add_log("info", "subscription", "\u8ba2\u9605\u641c\u7d22\u5df2\u52a0\u5165\u540e\u53f0\u961f\u5217", {"id": subscription_id})
    return {"ok": True, "queued": True, "running": True, "id": subscription_id}


async def _search_subscription_in_worker_thread(subscription_id: int) -> None:
    """Run expensive subscription search on a separate event loop in a worker thread."""
    await asyncio.to_thread(_run_subscription_search_sync, subscription_id)


def _run_subscription_search_sync(subscription_id: int) -> None:
    asyncio.run(_search_subscription_background_worker(subscription_id))


async def _search_all_background(
    *,
    search_all_func: Callable[[], Awaitable[dict]] | None = None,
) -> None:
    try:
        await asyncio.sleep(runtime.SEARCH_ALL_START_DELAY_SECONDS)
        search_all_func = search_all_func or _default_search_all
        await search_all_func()
    except Exception as exc:
        add_log("error", "subscription", "搜索全部活跃订阅后台任务失败", {"error": str(exc), "error_type": type(exc).__name__})
    finally:
        runtime.search_all_task = None


def schedule_search_all_active_subscriptions() -> dict:
    if runtime.search_all_task and not runtime.search_all_task.done():
        return {"ok": True, "queued": False, "running": True}
    runtime.search_all_task = asyncio.create_task(_search_all_in_worker_thread())
    add_log("info", "subscription", "搜索全部活跃订阅已加入后台队列")
    return {"ok": True, "queued": True, "running": True}


async def _search_all_in_worker_thread(
    *,
    search_all_func: Callable[[], Awaitable[dict]] | None = None,
) -> None:
    """Run manual search-all outside the API event loop to keep the frontend responsive."""
    await asyncio.to_thread(_run_search_all_sync, search_all_func)


def _run_search_all_sync(search_all_func: Callable[[], Awaitable[dict]] | None) -> None:
    asyncio.run(_search_all_background(search_all_func=search_all_func))


async def _emby_sync_background(
    *,
    sync_func: Callable[[], Awaitable[dict]] | None = None,
) -> None:
    try:
        await asyncio.sleep(runtime.EMBY_SYNC_START_DELAY_SECONDS)
        sync_func = sync_func or _default_emby_sync
        result = await sync_func()
        level = "info" if result.get("ok") else "warning"
        add_log(
            level,
            "emby",
            "\u624b\u52a8 Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u5b8c\u6210" if result.get("ok") else "\u624b\u52a8 Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u5931\u8d25",
            result,
        )
    except Exception as exc:
        add_log("error", "emby", "\u624b\u52a8 Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u540e\u53f0\u4efb\u52a1\u5931\u8d25", {"error": str(exc), "error_type": type(exc).__name__})
    finally:
        runtime.emby_sync_task = None


def schedule_emby_subscription_sync() -> dict:
    task = runtime.emby_sync_task
    if task and not task.done():
        return {"ok": True, "queued": False, "running": True}
    runtime.emby_sync_task = asyncio.create_task(_emby_sync_in_worker_thread())
    add_log("info", "emby", "\u624b\u52a8 Emby \u5165\u5e93\u72b6\u6001\u540c\u6b65\u5df2\u52a0\u5165\u540e\u53f0\u961f\u5217")
    return {"ok": True, "queued": True, "running": True}


async def _emby_sync_in_worker_thread(
    *,
    sync_func: Callable[[], Awaitable[dict]] | None = None,
) -> None:
    """Run manual Emby subscription sync outside the API event loop."""
    await asyncio.to_thread(_run_emby_sync_sync, sync_func)


def _run_emby_sync_sync(sync_func: Callable[[], Awaitable[dict]] | None) -> None:
    asyncio.run(_emby_sync_background(sync_func=sync_func))
