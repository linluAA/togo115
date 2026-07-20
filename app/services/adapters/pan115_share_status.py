from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.services.adapters.pan115_state import add_log

SHARE_AVAILABLE = "available"
SHARE_UNAVAILABLE = "unavailable"
SHARE_UNKNOWN = "unknown"
SHARE_AUTH_REQUIRED = "auth_required"
SHARE_RATE_LIMITED = "rate_limited"

SHARE_SNAP_URL = "https://webapi.115.com/share/snap"

# TTL seconds by status family.
_CACHE_TTL = {
    SHARE_AVAILABLE: 600,
    SHARE_UNAVAILABLE: 3600,
    SHARE_AUTH_REQUIRED: 120,
    SHARE_RATE_LIMITED: 60,
    SHARE_UNKNOWN: 45,
}

_UNAVAILABLE_ERRNOS = {
    4100001,
    4100002,
    4100003,
    4100004,
    4100005,
    4100008,
    4100010,
    4100013,
}
_AUTH_ERRNOS = {99, 401, 40101007, 40101010, 40101017}
_RATE_ERRNOS = {429, 911, 990001}

_UNAVAILABLE_WORDS = (
    "不存在",
    "取消",
    "过期",
    "失效",
    "提取码",
    "访问码",
    "错误",
    "invalid",
    "expired",
    "not found",
    "not exist",
    "share not found",
)
_PASSWORD_WORDS = ("提取码", "访问码", "password", "receive_code", "pwd")
_EXPIRED_WORDS = ("过期", "失效", "expired")
_CANCELLED_WORDS = ("取消", "cancelled", "canceled")
_AUTH_WORDS = ("登录", "登陆", "未登录", "cookie", "请先登录", "重新登录", "unauthorized", "auth")
_RATE_WORDS = ("频繁", "限流", "稍后", "too many", "rate", "busy")


@dataclass(frozen=True)
class ShareAvailability:
    status: str
    reason: str = ""
    cached: bool = False
    message: str = ""

    @property
    def legacy_status(self) -> str:
        if self.status == SHARE_AVAILABLE:
            return SHARE_AVAILABLE
        if self.status == SHARE_UNAVAILABLE:
            return SHARE_UNAVAILABLE
        return SHARE_UNKNOWN

    @property
    def reason_label(self) -> str:
        labels = {
            "ok": "可用",
            "invalid_link": "链接格式无效",
            "cookie_missing": "115 Cookie 未配置",
            "cookie_invalid": "115 Cookie 失效",
            "not_found": "分享不存在",
            "expired": "分享已过期",
            "cancelled": "分享已取消",
            "password_error": "提取码错误",
            "rate_limited": "请求被限流",
            "http_error": "检测请求失败",
            "server_error": "115 服务异常",
            "network_error": "网络异常",
            "parse_error": "响应解析失败",
            "empty_share": "分享内容为空",
            "haisou_valid": "海搜备用检测可用",
            "haisou_unknown": "海搜备用检测结果未知",
        }
        return labels.get(self.reason, self.reason or self.status)


_cache_lock = threading.Lock()
_share_cache: dict[str, tuple[float, ShareAvailability]] = {}


def clear_share_availability_cache() -> None:
    with _cache_lock:
        _share_cache.clear()


def cache_key_for_link(share_code: str, receive_code: str | None) -> str:
    return f"{share_code.casefold()}|{(receive_code or '').casefold()}"


def _cache_get(key: str) -> ShareAvailability | None:
    now = time.monotonic()
    with _cache_lock:
        item = _share_cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            _share_cache.pop(key, None)
            return None
        return ShareAvailability(status=value.status, reason=value.reason, cached=True, message=value.message)


def _cache_set(key: str, value: ShareAvailability) -> ShareAvailability:
    ttl = _CACHE_TTL.get(value.status, _CACHE_TTL[SHARE_UNKNOWN])
    stored = ShareAvailability(status=value.status, reason=value.reason, cached=False, message=value.message)
    with _cache_lock:
        _share_cache[key] = (time.monotonic() + ttl, stored)
        if len(_share_cache) > 2048:
            # Drop oldest ~10% when the cache grows too large.
            oldest = sorted(_share_cache.items(), key=lambda item: item[1][0])[:200]
            for old_key, _ in oldest:
                _share_cache.pop(old_key, None)
    return stored


def _payload_message(payload: dict[str, Any]) -> str:
    return str(
        payload.get("message")
        or payload.get("msg")
        or payload.get("error")
        or payload.get("errno_msg")
        or payload.get("err_msg")
        or ""
    )


def _payload_errno(payload: dict[str, Any]) -> int | None:
    for key in ("errno", "errcode", "code", "error_code"):
        if key not in payload or payload.get(key) in (None, ""):
            continue
        try:
            return int(payload.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _has_share_data(payload: dict[str, Any]) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    for key in ("list", "share_list", "file_list", "items"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return True
    count = data.get("count")
    try:
        if count is not None and int(count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    # Some responses only include share metadata without paging list when limit is tiny.
    for key in ("share_title", "total_size", "file_size", "snap_id", "user_id"):
        if data.get(key) not in (None, "", 0, "0"):
            return True
    return False


def classify_share_payload(payload: dict[str, Any]) -> ShareAvailability:
    if not isinstance(payload, dict):
        return ShareAvailability(SHARE_UNKNOWN, "parse_error", message="non-dict payload")

    message = _payload_message(payload)
    message_fold = message.casefold()
    errno = _payload_errno(payload)
    state = payload.get("state")

    if state is True or errno == 0 or payload.get("errcode") == 0 or payload.get("code") == 0:
        if _has_share_data(payload) or state is True or errno == 0:
            return ShareAvailability(SHARE_AVAILABLE, "ok", message=message)
        return ShareAvailability(SHARE_AVAILABLE, "ok", message=message or "empty data accepted by state/errno")

    if errno in _AUTH_ERRNOS or any(word in message_fold for word in _AUTH_WORDS):
        return ShareAvailability(SHARE_AUTH_REQUIRED, "cookie_invalid", message=message)

    if errno in _RATE_ERRNOS or any(word in message_fold for word in _RATE_WORDS):
        return ShareAvailability(SHARE_RATE_LIMITED, "rate_limited", message=message)

    if errno in _UNAVAILABLE_ERRNOS:
        reason = "not_found"
        if any(word in message_fold for word in _PASSWORD_WORDS):
            reason = "password_error"
        elif any(word in message_fold for word in _EXPIRED_WORDS):
            reason = "expired"
        elif any(word in message_fold for word in _CANCELLED_WORDS):
            reason = "cancelled"
        return ShareAvailability(SHARE_UNAVAILABLE, reason, message=message)

    if any(word in message_fold for word in _PASSWORD_WORDS) and any(
        word in message_fold for word in ("错误", "不正确", "无效", "invalid", "wrong", "error")
    ):
        return ShareAvailability(SHARE_UNAVAILABLE, "password_error", message=message)

    if any(word in message_fold for word in _EXPIRED_WORDS):
        return ShareAvailability(SHARE_UNAVAILABLE, "expired", message=message)

    if any(word in message_fold for word in _CANCELLED_WORDS):
        return ShareAvailability(SHARE_UNAVAILABLE, "cancelled", message=message)

    if any(word in message_fold for word in ("不存在", "not found", "not exist", "share not found")):
        return ShareAvailability(SHARE_UNAVAILABLE, "not_found", message=message)

    if any(word in message_fold for word in _UNAVAILABLE_WORDS):
        return ShareAvailability(SHARE_UNAVAILABLE, "not_found", message=message)

    if state is False and errno not in (None, 0):
        # Unknown business code without clear wording: treat as unavailable only when
        # there is also no share payload data.
        if not _has_share_data(payload):
            return ShareAvailability(SHARE_UNAVAILABLE, "not_found", message=message or f"errno={errno}")

    return ShareAvailability(SHARE_UNKNOWN, "parse_error", message=message or f"errno={errno}")


def _share_available_payload(payload: dict[str, Any]) -> bool:
    return classify_share_payload(payload).status == SHARE_AVAILABLE

