from __future__ import annotations

import asyncio
from typing import Any

from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_AVAILABLE, Pan115Adapter

# Cap concurrent live 115 probes across the process (cache hits bypass this).
SHARE_115_PROBE_CONCURRENCY = 3


class Shared115ValidationCache:
    """Process-wide 115 availability helper for concurrent subscription searches.

    Pan115 already keeps a TTL cache of share probes. This layer adds:
    - one adapter instance for the process burst
    - in-flight de-duplication so identical URLs only hit the network once
    - limited concurrency for live probes to avoid serial attach latency
    """

    def __init__(self, *, probe_concurrency: int = SHARE_115_PROBE_CONCURRENCY) -> None:
        self._adapter: Any | None = None
        self._inflight: dict[str, asyncio.Future[str]] = {}
        self._probe_semaphore = asyncio.Semaphore(max(1, int(probe_concurrency or 1)))
        self.checked = 0
        self.coalesced = 0

    def _get_adapter(self) -> Any:
        # Resolve after construction so tests can patch Pan115Adapter first.
        if self._adapter is None:
            self._adapter = Pan115Adapter()
        return self._adapter

    async def availability(self, url: str) -> str:
        value = str(url or "")
        if not PAN115_URL_RE.match(value):
            return SHARE_AVAILABLE
        existing = self._inflight.get(value)
        if existing is not None and not existing.done():
            self.coalesced += 1
            return await asyncio.shield(existing)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._inflight[value] = future
        try:
            async with self._probe_semaphore:
                state = await self._get_adapter().share_availability(value)
            self.checked += 1
            if not future.done():
                future.set_result(state)
            return state
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            current = self._inflight.get(value)
            if current is future:
                self._inflight.pop(value, None)

    async def availability_many(self, urls: list[str]) -> dict[str, str]:
        """Probe many URLs with bounded concurrency; returns url->state map."""
        unique: list[str] = []
        seen: set[str] = set()
        for url in urls:
            value = str(url or "")
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        if not unique:
            return {}
        states = await asyncio.gather(*(self.availability(url) for url in unique), return_exceptions=True)
        out: dict[str, str] = {}
        for url, state in zip(unique, states):
            if isinstance(state, Exception):
                continue
            out[url] = str(state)
        return out

    def stats(self) -> dict[str, int]:
        return {"checked": self.checked, "coalesced": self.coalesced}


_PROCESS_CACHE: Shared115ValidationCache | None = None


def process_115_cache() -> Shared115ValidationCache:
    global _PROCESS_CACHE
    if _PROCESS_CACHE is None:
        _PROCESS_CACHE = Shared115ValidationCache()
    return _PROCESS_CACHE


def reset_process_115_cache() -> None:
    """Drop the process cache (tests / adapter reconfiguration)."""
    global _PROCESS_CACHE
    _PROCESS_CACHE = None
