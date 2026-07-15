from __future__ import annotations

import asyncio
import time


class TelegramRequestGate:
    """Simple process-wide spacing gate to reduce FloodWait under multi-subscription search."""

    def __init__(self, min_interval_seconds: float = 0.05) -> None:
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._next_at = 0.0

    def _ensure_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
            self._next_at = 0.0
        return self._lock

    async def wait(self) -> None:
        if self._min_interval <= 0:
            return
        lock = self._ensure_lock()
        async with lock:
            now = time.monotonic()
            delay = self._next_at - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next_at = now + self._min_interval


telegram_request_gate = TelegramRequestGate(0.05)
