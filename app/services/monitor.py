import asyncio
import time
from contextlib import suppress

from app.config import settings
from app.db import add_log, db, utc_now
from app.services.integrations import TelegramClientAdapter
from app.services.subscription import list_subscriptions, search_and_attach_resources, sync_subscriptions_with_emby


class MonitorService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_emby_sync = 0.0
        self._last_log_cleanup = 0.0

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
        add_log("info", "monitor", "订阅监控已停止")

    async def _run(self) -> None:
        telegram = TelegramClientAdapter()
        # 优化1: 并发搜索 Semaphore，限制同时搜索的订阅数量
        search_sem = asyncio.Semaphore(3)
        while not self._stopping.is_set():
            try:
                await telegram.ensure_monitoring()
                if time.monotonic() - self._last_emby_sync > 600:
                    await sync_subscriptions_with_emby()
                    self._last_emby_sync = time.monotonic()
                # 优化6: 每 6 小时清理一次 7 天前的 debug 日志
                if time.monotonic() - self._last_log_cleanup > 21600:
                    self._cleanup_old_logs()
                    self._last_log_cleanup = time.monotonic()
                active = [s for s in list_subscriptions() if s["status"] == "active"]
                # 优化1: 并发搜索所有活跃订阅
                async def _search_limited(sub: dict) -> None:
                    async with search_sem:
                        await search_and_attach_resources(sub["id"])
                await asyncio.gather(*[_search_limited(s) for s in active])
            except Exception as exc:
                add_log("error", "monitor", "监控循环异常，下一轮将自动重试", {"error": str(exc)})
            await asyncio.sleep(settings.monitor_interval_seconds)

    def _cleanup_old_logs(self) -> None:
        """优化6: 清理 7 天前的 debug 日志，防止日志表无限膨胀。"""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with db() as conn:
            cursor = conn.execute("DELETE FROM logs WHERE level = 'debug' AND created_at < ?", (cutoff,))
            deleted = cursor.rowcount
        if deleted:
            add_log("info", "monitor", "已清理过期 debug 日志", {"deleted": deleted})


monitor_service = MonitorService()
