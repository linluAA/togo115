from __future__ import annotations

import asyncio
import time
from typing import Any

from app.db import add_log
from app.services.adapters.media import EmbyAdapter
from app.services.subscription.library.match import _emby_configured


EMBY_SNAPSHOT_FAILED: dict[str, list[dict[str, Any]]] = {"__failed__": []}
# Large libraries need more than 20s when episode pages are many.
EMBY_SNAPSHOT_TIMEOUT_SECONDS = 90
EMBY_SNAPSHOT_CACHE_TTL_SECONDS = 600
# Keep stale cache much longer so a temporary Emby outage still has a usable map.
EMBY_SNAPSHOT_STALE_TTL_SECONDS = 6 * 3600
EMBY_SYNC_TIMEOUT_SECONDS = 90
_emby_snapshot_cache: tuple[float, dict[str, list[dict[str, Any]]]] | None = None
_emby_snapshot_lock: asyncio.Lock | None = None
_emby_snapshot_lock_loop: int | None = None


def reset_library_snapshot_cache() -> None:
    """Clear the in-process Emby library snapshot cache."""
    global _emby_snapshot_cache
    _emby_snapshot_cache = None


def _snapshot_lock() -> asyncio.Lock:
    global _emby_snapshot_lock, _emby_snapshot_lock_loop
    loop_id = id(asyncio.get_running_loop())
    if _emby_snapshot_lock is None or _emby_snapshot_lock_loop != loop_id:
        _emby_snapshot_lock = asyncio.Lock()
        _emby_snapshot_lock_loop = loop_id
    return _emby_snapshot_lock


def _cache_age_seconds() -> float | None:
    if not _emby_snapshot_cache:
        return None
    return max(0.0, time.time() - float(_emby_snapshot_cache[0]))


def _cached_snapshot(*, allow_stale: bool) -> dict[str, list[dict[str, Any]]] | None:
    if not _emby_snapshot_cache:
        return None
    age = _cache_age_seconds() or 0.0
    if age <= EMBY_SNAPSHOT_CACHE_TTL_SECONDS:
        return _emby_snapshot_cache[1]
    if allow_stale and age <= EMBY_SNAPSHOT_STALE_TTL_SECONDS:
        return _emby_snapshot_cache[1]
    return None


async def library_snapshot_or_none(force: bool = False) -> dict[str, list[dict[str, Any]]] | None:
    """Return Emby library snapshot, with fresh/stale cache and single-flight refresh.

    Returns:
      - None: Emby not configured
      - EMBY_SNAPSHOT_FAILED: refresh failed and no usable cache
      - dict snapshot: success (fresh or stale fallback)
    """
    global _emby_snapshot_cache
    if not _emby_configured():
        return None

    if not force:
        cached = _cached_snapshot(allow_stale=False)
        if cached is not None:
            age = _cache_age_seconds() or 0.0
            add_log(
                "debug",
                "emby",
                "复用 Emby 媒体库快照缓存",
                {
                    "age_seconds": round(age, 1),
                    "movies": len(cached.get("movies", [])),
                    "series": len(cached.get("series", [])),
                    "episodes": len(cached.get("episodes", [])),
                },
            )
            return cached

    async with _snapshot_lock():
        if not force:
            cached = _cached_snapshot(allow_stale=False)
            if cached is not None:
                return cached
        return await _refresh_library_snapshot(force=force)


async def _refresh_library_snapshot(*, force: bool) -> dict[str, list[dict[str, Any]]]:
    global _emby_snapshot_cache
    started = time.perf_counter()
    try:
        add_log("debug", "emby", "开始获取 Emby 媒体库快照", {"force": bool(force), "timeout": EMBY_SNAPSHOT_TIMEOUT_SECONDS})
        snapshot = await asyncio.wait_for(
            EmbyAdapter().library_snapshot(),
            timeout=EMBY_SNAPSHOT_TIMEOUT_SECONDS,
        )
        if not isinstance(snapshot, dict):
            raise RuntimeError("invalid snapshot payload")
        # Guard against accidental failed marker being cached.
        if "__failed__" in snapshot:
            raise RuntimeError("snapshot failed marker")
        _emby_snapshot_cache = (time.time(), snapshot)
        add_log(
            "info",
            "emby",
            "Emby 媒体库快照获取完成",
            {
                "movies": len(snapshot.get("movies", [])),
                "series": len(snapshot.get("series", [])),
                "episodes": len(snapshot.get("episodes", [])),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return snapshot
    except asyncio.TimeoutError:
        return _failed_or_stale(
            reason="timeout",
            detail={"timeout": EMBY_SNAPSHOT_TIMEOUT_SECONDS, "elapsed_ms": int((time.perf_counter() - started) * 1000)},
        )
    except Exception as exc:
        return _failed_or_stale(
            reason="error",
            detail={
                "error": str(exc),
                "error_type": type(exc).__name__,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )


def _failed_or_stale(*, reason: str, detail: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    stale = _cached_snapshot(allow_stale=True)
    if stale is not None:
        age = _cache_age_seconds() or 0.0
        add_log(
            "warning",
            "emby",
            "Emby 快照刷新失败，已回退到旧缓存",
            {
                "reason": reason,
                "age_seconds": round(age, 1),
                "movies": len(stale.get("movies", [])),
                "series": len(stale.get("series", [])),
                "episodes": len(stale.get("episodes", [])),
                **detail,
            },
        )
        return stale
    message = "Emby 快照获取超时" if reason == "timeout" else "Emby 快照获取失败"
    add_log("warning", "emby", f"{message}，且无可用缓存", {"reason": reason, **detail})
    return EMBY_SNAPSHOT_FAILED
