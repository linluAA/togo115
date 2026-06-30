import asyncio
import time
from contextlib import suppress

from app.config import settings
from app.db import add_log
from app.services.integrations import TelegramBotAdapter, TelegramClientAdapter
from app.services.subscription import list_subscriptions, search_and_attach_resources, sync_subscriptions_with_emby


class MonitorService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_emby_sync = 0.0
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
                if time.monotonic() - self._last_emby_sync > 600:
                    await sync_subscriptions_with_emby()
                    self._last_emby_sync = time.monotonic()
                for subscription in list_subscriptions():
                    if subscription["status"] == "active":
                        await search_and_attach_resources(subscription["id"])
            except Exception as exc:
                add_log("error", "monitor", "监控循环异常，下一轮将自动重试", {"error": str(exc)})
            await asyncio.sleep(settings.monitor_interval_seconds)


monitor_service = MonitorService()
