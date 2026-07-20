from __future__ import annotations

from typing import Any

import httpx

from app.services.adapters.pan115_state import add_log
from app.services.adapters.pan115_share_status import (
    SHARE_AUTH_REQUIRED,
    SHARE_AVAILABLE,
    SHARE_RATE_LIMITED,
    SHARE_SNAP_URL,
    SHARE_UNAVAILABLE,
    SHARE_UNKNOWN,
    ShareAvailability,
    _cache_get,
    _cache_set,
    _payload_errno,
    _payload_message,
    _share_available_payload,
    cache_key_for_link,
    classify_share_payload,
    clear_share_availability_cache,
)

# Re-export public symbols for existing importers.
__all__ = [
    "SHARE_AVAILABLE",
    "SHARE_UNAVAILABLE",
    "SHARE_UNKNOWN",
    "SHARE_AUTH_REQUIRED",
    "SHARE_RATE_LIMITED",
    "ShareAvailability",
    "clear_share_availability_cache",
    "cache_key_for_link",
    "classify_share_payload",
    "probe_share_availability",
]


async def probe_share_availability(
    *,
    link: str,
    share_code: str,
    receive_code: str | None,
    cookie: str | None,
    client_factory,
    normalize_link,
) -> ShareAvailability:
    clean_link = normalize_link(link)
    if not clean_link or not share_code:
        add_log("info", "115", "115 分享链接格式无效", {"link": str(link or "")[:240]})
        return ShareAvailability(SHARE_UNAVAILABLE, "invalid_link")

    cache_key = cache_key_for_link(share_code, receive_code)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not cookie:
        add_log("warning", "115", "115 Cookie 尚未配置，尝试海搜备用检测", {"link": clean_link})
        fallback = await _fallback_with_haisou(clean_link, receive_code, trigger="cookie_missing")
        if fallback is not None:
            return _cache_set(cache_key, fallback)
        result = ShareAvailability(SHARE_AUTH_REQUIRED, "cookie_missing")
        add_log("warning", "115", "115 Cookie 尚未配置，分享有效性待复检", {"link": clean_link})
        return _cache_set(cache_key, result)

    headers = {"Referer": clean_link, "Cookie": cookie}
    params = {
        "share_code": share_code,
        "receive_code": receive_code or "",
        "offset": 0,
        "limit": 1,
    }
    try:
        async with client_factory() as client:
            res = await client.get(SHARE_SNAP_URL, params=params, headers=headers)
    except (UnicodeEncodeError, httpx.InvalidURL) as exc:
        result = ShareAvailability(SHARE_UNAVAILABLE, "invalid_link", message=repr(exc))
        add_log(
            "warning",
            "115",
            "115 分享链接格式异常，已判定不可用",
            {"link": str(link or "")[:240], "clean_link": clean_link, "error": repr(exc)},
        )
        return _cache_set(cache_key, result)
    except Exception as exc:
        result = ShareAvailability(SHARE_UNKNOWN, "network_error", message=f"{type(exc).__name__}: {exc}")
        add_log(
            "warning",
            "115",
            "115 分享有效性检测异常，已标记待复检",
            {
                "link": clean_link,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "error_repr": repr(exc),
            },
        )
        return _cache_set(cache_key, result)

    if res.status_code in {404, 410}:
        result = ShareAvailability(SHARE_UNAVAILABLE, "not_found", message=f"http={res.status_code}")
        add_log("info", "115", "115 分享链接不可用", {"link": clean_link, "status": res.status_code, "reason": result.reason})
        return _cache_set(cache_key, result)
    if res.status_code == 429:
        result = ShareAvailability(SHARE_RATE_LIMITED, "rate_limited", message="http=429")
        add_log("warning", "115", "115 分享有效性检测被限流，已标记待复检", {"link": clean_link})
        return _cache_set(cache_key, result)
    if res.status_code >= 500:
        result = ShareAvailability(SHARE_UNKNOWN, "server_error", message=f"http={res.status_code}")
        add_log("warning", "115", "115 分享有效性检测服务异常，已标记待复检", {"status": res.status_code, "link": clean_link})
        return _cache_set(cache_key, result)
    if res.status_code >= 400:
        result = ShareAvailability(SHARE_UNKNOWN, "http_error", message=f"http={res.status_code}")
        add_log("warning", "115", "115 分享有效性检测请求失败，已标记待复检", {"status": res.status_code, "link": clean_link})
        return _cache_set(cache_key, result)

    try:
        payload = res.json()
    except Exception as exc:
        result = ShareAvailability(SHARE_UNKNOWN, "parse_error", message=repr(exc))
        add_log("warning", "115", "115 分享有效性检测响应解析失败，已标记待复检", {"link": clean_link, "error": repr(exc)})
        return _cache_set(cache_key, result)

    result = classify_share_payload(payload if isinstance(payload, dict) else {})
    if result.status == SHARE_UNAVAILABLE:
        add_log(
            "info",
            "115",
            "115 分享链接不可用",
            {"link": clean_link, "reason": result.reason, "message": result.message, "response": payload},
        )
    elif result.status == SHARE_AUTH_REQUIRED:
        add_log(
            "warning",
            "115",
            "115 Cookie 可能失效，尝试海搜备用检测",
            {"link": clean_link, "message": result.message},
        )
        fallback = await _fallback_with_haisou(clean_link, receive_code, trigger="cookie_invalid")
        if fallback is not None:
            return _cache_set(cache_key, fallback)
        add_log("warning", "115", "115 Cookie 可能失效，分享有效性待复检", {"link": clean_link, "message": result.message})
    elif result.status in {SHARE_UNKNOWN, SHARE_RATE_LIMITED}:
        add_log(
            "warning",
            "115",
            "115 分享有效性未知，已标记待复检",
            {"link": clean_link, "status": result.status, "reason": result.reason, "message": result.message},
        )
    return _cache_set(cache_key, result)


async def _fallback_with_haisou(
    link: str,
    receive_code: str | None,
    *,
    trigger: str,
) -> ShareAvailability | None:
    from app.services.adapters.pan115_share_haisou import try_haisou_share_fallback

    return await try_haisou_share_fallback(link=link, receive_code=receive_code, trigger=trigger)
