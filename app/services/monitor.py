import asyncio
import time
from contextlib import suppress

from app.config import settings
from app.db import add_log
from app.services.adapters.telegram import TelegramBotAdapter, TelegramClientAdapter
from app.services.subscription import (
    list_subscriptions,
    recheck_pending_115_resources,
    retry_failed_resources,
    schedule_search_all_active_subscriptions,
    sync_subscription_list_with_emby,
)


class MonitorService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_emby_sync = 0.0
        self._last_recheck = 0.0
        self._last_index_prewarm = 0.0
        self._last_subscription_rescan = 0.0
        self._last_failed_retry = 0.0
        self._bot = TelegramBotAdapter()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="togo115-monitor")
        add_log("info", "monitor", "\u8ba2\u9605\u76d1\u63a7\u5df2\u542f\u52a8")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self._bot.stop_polling()
        add_log("info", "monitor", "\u8ba2\u9605\u76d1\u63a7\u5df2\u505c\u6b62")

    async def _run(self) -> None:
        telegram = TelegramClientAdapter()
        while not self._stopping.is_set():
            try:
                await telegram.ensure_monitoring()
                await self._bot.ensure_polling()
                now = time.monotonic()
                if now - self._last_recheck > 120:
                    await recheck_pending_115_resources()
                    self._last_recheck = now
                if now - self._last_failed_retry > 300:
                    result = await retry_failed_resources(12)
                    if int(result.get("retried") or 0):
                        add_log(
                            "info",
                            "monitor",
                            "失败任务智能重试完成",
                            result,
                        )
                    self._last_failed_retry = now
                if now - self._last_index_prewarm > 900:
                    try:
                        await telegram.prewarm_message_index()
                    except Exception as exc:
                        add_log(
                            "warning",
                            "monitor",
                            "Telegram \u7d22\u5f15\u9884\u70ed\u5f02\u5e38",
                            {"error": str(exc), "error_type": type(exc).__name__},
                        )
                    self._last_index_prewarm = now
                if now - self._last_emby_sync > 600:
                    await sync_subscription_list_with_emby(list_subscriptions(include_completed=True))
                    self._last_emby_sync = now
                self._maybe_schedule_subscription_rescan(now)
            except Exception as exc:
                add_log(
                    "error",
                    "monitor",
                    "\u76d1\u63a7\u5faa\u73af\u5f02\u5e38\uff0c\u4e0b\u4e00\u8f6e\u5c06\u81ea\u52a8\u91cd\u8bd5",
                    {"error": str(exc)},
                )
            await asyncio.sleep(settings.monitor_interval_seconds)

    def _maybe_schedule_subscription_rescan(self, now: float | None = None) -> dict | None:
        interval = int(getattr(settings, "subscription_rescan_interval_seconds", 0) or 0)
        if interval <= 0:
            return None
        current = time.monotonic() if now is None else now
        if self._last_subscription_rescan <= 0:
            self._last_subscription_rescan = current
            return None
        if current - self._last_subscription_rescan < interval:
            return None
        result = schedule_search_all_active_subscriptions()
        self._last_subscription_rescan = current
        add_log(
            "info",
            "monitor",
            "\u5df2\u6309\u8ba1\u5212\u89e6\u53d1\u5168\u90e8\u6d3b\u8dc3\u8ba2\u9605\u91cd\u641c",
            {
                "interval_seconds": interval,
                "queued": bool(result.get("queued")),
                "running": bool(result.get("running")),
            },
        )
        return result


monitor_service = MonitorService()
