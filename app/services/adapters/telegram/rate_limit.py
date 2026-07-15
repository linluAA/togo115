from __future__ import annotations

import asyncio
import time
from typing import Any


class TelegramRequestGate:
    """Process-wide spacing gate with adaptive backoff after FloodWait-like errors."""

    def __init__(
        self,
        min_interval_seconds: float = 0.05,
        *,
        max_interval_seconds: float = 2.0,
        default_interval_seconds: float = 0.05,
    ) -> None:
        self._default_interval = max(0.0, float(default_interval_seconds))
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._max_interval = max(self._min_interval, float(max_interval_seconds))
        self._current_interval = self._default_interval
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._next_at = 0.0
        self._cooldown_until = 0.0
        self.flood_events = 0

    def _ensure_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
            self._next_at = 0.0
            self._cooldown_until = 0.0
        return self._lock

    @property
    def interval(self) -> float:
        return self._current_interval

    async def wait(self) -> None:
        lock = self._ensure_lock()
        async with lock:
            now = time.monotonic()
            target = max(self._next_at, self._cooldown_until)
            delay = target - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next_at = now + self._current_interval
            # Gradually recover toward the default interval after a quiet period.
            if self._current_interval > self._default_interval and now >= self._cooldown_until:
                self._current_interval = max(self._default_interval, self._current_interval * 0.85)

    def note_success(self) -> None:
        if self._current_interval <= self._default_interval:
            return
        self._current_interval = max(self._default_interval, self._current_interval * 0.9)

    def note_flood_wait(self, seconds: float | None = None) -> None:
        """Increase spacing after FloodWait or similar rate-limit signals."""
        wait_for = max(1.0, float(seconds or 5.0))
        self.flood_events += 1
        self._current_interval = min(self._max_interval, max(self._current_interval * 2.0, wait_for / 10.0, 0.2))
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + wait_for)
        self._next_at = max(self._next_at, self._cooldown_until)

    def note_error(self, exc: Any = None) -> None:
        name = type(exc).__name__ if exc is not None else ""
        text = str(exc or "")
        if "FloodWait" in name or "FloodWait" in text or "flood" in text.casefold():
            seconds = getattr(exc, "seconds", None)
            try:
                self.note_flood_wait(float(seconds) if seconds is not None else 5.0)
            except Exception:
                self.note_flood_wait(5.0)

    def stats(self) -> dict[str, float | int]:
        return {
            "interval": round(self._current_interval, 3),
            "flood_events": self.flood_events,
            "cooldown_remaining": max(0.0, round(self._cooldown_until - time.monotonic(), 2)),
        }


telegram_request_gate = TelegramRequestGate(0.05)
