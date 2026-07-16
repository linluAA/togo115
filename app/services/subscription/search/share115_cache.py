from __future__ import annotations

import asyncio
from typing import Any

from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_AVAILABLE, Pan115Adapter


class Shared115ValidationCache:
    """Process-wide 115 availability helper for concurrent subscription searches.

    Pan115 already keeps a TTL cache of share probes. This layer adds:
    - one adapter instance for the process burst
    - in-flight de-duplication so identical URLs only hit the network once
    """

    def __init__(self) -> None:
        self._adapter = Pan115Adapter()
        self._inflight: dict[str, asyncio.Future[str]] = {}
        self.checked = 0
        self.coalesced = 0

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
            state = await self._adapter.share_availability(value)
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

    def stats(self) -> dict[str, int]:
        return {"checked": self.checked, "coalesced": self.coalesced}


_PROCESS_CACHE: Shared115ValidationCache | None = None


def process_115_cache() -> Shared115ValidationCache:
    global _PROCESS_CACHE
    if _PROCESS_CACHE is None:
        _PROCESS_CACHE = Shared115ValidationCache()
    return _PROCESS_CACHE
