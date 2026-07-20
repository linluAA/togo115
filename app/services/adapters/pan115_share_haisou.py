from __future__ import annotations

from typing import Any

from app.services.adapters.pan115_share_status import (
    SHARE_AVAILABLE,
    SHARE_UNAVAILABLE,
    SHARE_UNKNOWN,
    ShareAvailability,
)
from app.services.adapters.pan115_state import add_log
from app.services.sources.haisou.budget import (
    allow_haisou_validate,
    get_cached_haisou_validate,
    note_haisou_validate,
    set_cached_haisou_validate,
    validate_cache_key,
)


def classify_haisou_validate_result(result: dict[str, Any] | None) -> ShareAvailability:
    """Map Haisou validate API result into ShareAvailability."""
    payload = result if isinstance(result, dict) else {}
    valid = payload.get("valid")
    status = str(payload.get("status") or "").strip().lower()
    reason_text = str(payload.get("reason") or payload.get("msg") or payload.get("message") or "").strip()
    haystack = f"{status} {reason_text}".casefold()

    if valid is True or status in {"valid", "ok", "available", "alive", "active"}:
        return ShareAvailability(SHARE_AVAILABLE, "haisou_valid", message=reason_text or "haisou valid")

    if valid is False or status in {"invalid", "expired", "not_found", "unavailable", "dead", "cancelled", "canceled"}:
        reason = "not_found"
        if any(word in haystack for word in ("过期", "失效", "expir")):
            reason = "expired"
        elif any(word in haystack for word in ("取消", "cancel")):
            reason = "cancelled"
        elif any(word in haystack for word in ("提取码", "访问码", "password", "pwd", "receive_code")):
            reason = "password_error"
        return ShareAvailability(SHARE_UNAVAILABLE, reason, message=reason_text or status or "haisou invalid")

    # Ambiguous payload: do not override original auth failure with a hard unavailable.
    return ShareAvailability(SHARE_UNKNOWN, "haisou_unknown", message=reason_text or status or "haisou unknown")


async def try_haisou_share_fallback(
    *,
    link: str,
    receive_code: str | None,
    trigger: str,
) -> ShareAvailability | None:
    """Use Haisou validate only as Cookie-missing/invalid fallback.

    Returns None when Haisou is unavailable or request fails, so caller keeps original status.
    """
    try:
        from app.services.sources.haisou import HaisouApiError, HaisouClient, haisou_enabled
    except Exception as exc:
        add_log(
            "debug",
            "115",
            "海搜备用检测不可用",
            {"link": str(link or "")[:240], "trigger": trigger, "error": repr(exc)},
        )
        return None

    if not haisou_enabled():
        return None

    clean_link = str(link or "").strip()
    cache_key = validate_cache_key(clean_link, receive_code)
    cached = get_cached_haisou_validate(cache_key)
    if isinstance(cached, ShareAvailability):
        return cached
    if not allow_haisou_validate():
        add_log(
            "warning",
            "115",
            "海搜备用检测达到窗口预算，保留原 Cookie 状态",
            {"link": clean_link[:240], "trigger": trigger},
        )
        return None

    try:
        note_haisou_validate()
        result = await HaisouClient().validate(clean_link, pwd=receive_code)
    except HaisouApiError as exc:
        add_log(
            "warning",
            "115",
            "海搜备用检测失败，保留原 Cookie 状态",
            {
                "link": str(link or "")[:240],
                "trigger": trigger,
                "error": str(exc),
                "code": exc.code,
                "credits": exc.credits,
                "retryable": exc.retryable,
            },
        )
        return None
    except Exception as exc:
        add_log(
            "warning",
            "115",
            "海搜备用检测异常，保留原 Cookie 状态",
            {"link": str(link or "")[:240], "trigger": trigger, "error": repr(exc)},
        )
        return None

    info = classify_haisou_validate_result(result if isinstance(result, dict) else {})
    set_cached_haisou_validate(cache_key, info)
    add_log(
        "info" if info.status == SHARE_AVAILABLE else "warning",
        "115",
        "海搜备用检测完成",
        {
            "link": str(link or "")[:240],
            "trigger": trigger,
            "status": info.status,
            "reason": info.reason,
            "message": info.message,
        },
    )
    return info
