import asyncio
import time
from contextlib import suppress

from app.config import settings
from app.db import add_log
from app.services.adapters.telegram import TelegramBotAdapter, TelegramClientAdapter
from app.services.subscription import (
    list_subscriptions,
    recheck_pending_115_resources,
    schedule_search_all_active_subscriptions,
    sync_subscription_list_with_emby,
)


class MonitorService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_emby_sync = 0.0
        self._last_recheck = 0.0
        self._last_subscription_rescan = 0.0
        self._bot = TelegramBotAdapter()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="togo115-monitor")
        add_log("info", "monitor", "订阅监控已启动")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self._bot.stop_polling()
        add_log("info", "monitor", "订阅监控已停止")

    async def _run(self) -> None:
        telegram = TelegramClientAdapter()
        while not self._stopping.is_set():
            try:
                await telegram.ensure_monitoring()
                await self._bot.ensure_polling()
                now = time.monotonic()
                if now - self._last_recheck > 30:
                    await recheck_pending_115_resources()
                    self._last_recheck = now
                if now - self._last_emby_sync > 600:
                    await sync_subscription_list_with_emby(list_subscriptions(include_completed=True))
                    self._last_emby_sync = now
                self._maybe_schedule_subscription_rescan(now)
            except Exception as exc:
                add_log("error", "monitor", "监控循环异常，下一轮将自动重试", {"error": str(exc)})
            await asyncio.sleep(settings.monitor_interval_seconds)

    def _maybe_schedule_subscription_rescan(self, now: float | None = None) -> dict | None:
        """Queue a full active-subscription rescan when the interval has elapsed."""
        interval = int(getattr(settings, "subscription_rescan_interval_seconds", 0) or 0)
        if interval <= 0:
            return None
        current = time.monotonic() if now is None else now
        # First tick after start: arm the timer without scanning immediately.
        # New subscriptions already schedule their own search.
        if self._last_subscription_rescan <= 0:
            self._last_subscription_rescan = current
            return None
        if current - self._last_subscription_rescan < interval:
            return None
        result = schedule_search_all_active_subscriptions()
        # Always advance the timer so a long-running search doesn't re-trigger every monitor tick.
        self._last_subscription_rescan = current
        add_log(
            "info",
            "monitor",
            "已按计划触发全部活跃订阅重搜",
            {
                "interval_seconds": interval,
                "queued": bool(result.get("queued")),
                "running": bool(result.get("running")),
            },
        )
        return result


monitor_service = MonitorService()
