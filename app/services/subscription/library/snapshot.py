from __future__ import annotations

import asyncio
import time
from typing import Any

from app.db import add_log
from app.services.adapters.media import EmbyAdapter
from app.services.subscription.library.match import _emby_configured


EMBY_SNAPSHOT_FAILED: dict[str, list[dict[str, Any]]] = {"__failed__": []}
EMBY_SNAPSHOT_TIMEOUT_SECONDS = 20
EMBY_SNAPSHOT_CACHE_TTL_SECONDS = 600
EMBY_SYNC_TIMEOUT_SECONDS = 25
_emby_snapshot_cache: tuple[float, dict[str, list[dict[str, Any]]]] | None = None


def reset_library_snapshot_cache() -> None:
    """Clear the in-process Emby library snapshot cache."""
    global _emby_snapshot_cache
    _emby_snapshot_cache = None


async def _library_snapshot_or_none(force: bool = False) -> dict[str, list[dict[str, Any]]] | None:
    global _emby_snapshot_cache
    if not _emby_configured():
        return None
    if not force and _emby_snapshot_cache:
        cached_at, cached_snapshot = _emby_snapshot_cache
        age_seconds = time.time() - cached_at
        if age_seconds <= EMBY_SNAPSHOT_CACHE_TTL_SECONDS:
            add_log(
                "debug",
                "emby",
                "复用 Emby 媒体库快照缓存",
                {
                    "age_seconds": round(age_seconds, 1),
                    "movies": len(cached_snapshot.get("movies", [])),
                    "series": len(cached_snapshot.get("series", [])),
                    "episodes": len(cached_snapshot.get("episodes", [])),
                },
            )
            return cached_snapshot
    try:
        add_log("debug", "emby", "开始获取 Emby 媒体库快照")
        snapshot = await asyncio.wait_for(EmbyAdapter().library_snapshot(), timeout=EMBY_SNAPSHOT_TIMEOUT_SECONDS)
        add_log(
            "debug",
            "emby",
            "Emby 媒体库快照获取完成",
            {
                "movies": len(snapshot.get("movies", [])),
                "series": len(snapshot.get("series", [])),
                "episodes": len(snapshot.get("episodes", [])),
            },
        )
        _emby_snapshot_cache = (time.time(), snapshot)
        return snapshot
    except asyncio.TimeoutError:
        add_log("warning", "emby", "Emby 快照获取超时，本轮会跳过需要缺集判断的订阅", {"timeout": EMBY_SNAPSHOT_TIMEOUT_SECONDS})
        return EMBY_SNAPSHOT_FAILED
    except Exception as exc:
        add_log("warning", "emby", "Emby 快照获取失败，本轮会跳过需要缺集判断的订阅", {"error": str(exc)})
        return EMBY_SNAPSHOT_FAILED
