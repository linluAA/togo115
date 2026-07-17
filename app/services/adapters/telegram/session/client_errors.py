from __future__ import annotations

import asyncio
from typing import Any

from app.db import add_log


def classify_client_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc!s} {exc!r}".casefold()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if "api id/api hash" in text or "尚未配置" in text or "missing-config" in text:
        return "missing-config"
    if "database is locked" in text or "database table is locked" in text or "database locked" in text:
        return "session-locked"
    if (
        "file is not a database" in text
        or "database disk image is malformed" in text
        or "malformed" in text
        or "corrupt" in text
        or "no such table" in text
    ):
        return "session-corrupt"
    if (
        "auth key" in text
        or "unauthorized" in text
        or "session revoked" in text
        or "user deactivated" in text
        or "not logged in" in text
    ):
        return "auth"
    if (
        "proxy" in text
        or "socks" in text
        or "connection refused" in text
        or "connection reset" in text
        or "network" in text
        or "host unreachable" in text
        or "name or service not known" in text
        or "temporary failure" in text
        or "ssl" in text
        or "tls" in text
    ):
        return "network-or-proxy"
    return "unknown"


def log_client_init_failure(
    *,
    exc: Exception,
    category: str,
    action: str,
    recovered: bool,
    configured: dict[str, Any],
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "category": category,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "error_repr": repr(exc),
        "configured": configured,
        "action": action,
        "recovered": recovered,
    }
    if attempt is not None:
        payload["attempt"] = attempt
    if extra:
        payload.update(extra)
    add_log("warning", "telegram", "Telegram 客户端初始化失败", payload)
