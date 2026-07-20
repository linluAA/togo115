from __future__ import annotations

from typing import Any

from app.services.integration_state import get_setting, module_proxy
from app.services.link import truthy


SUPPORTED_PLATFORMS = ("115", "ali", "baidu", "quark", "xunlei", "tianyi", "yidong", "123", "uc")
DEFAULT_PLATFORMS = ("115",)
DEFAULT_PAGE_SIZE = 20
DEFAULT_SEARCH_IN = "title"
REQUEST_TIMEOUT_SECONDS = 75.0
SOURCE_PRIORITY = 10
SOURCE_ID = "builtin_haisou"
SOURCE_NAME = "海搜 Haisou"
SOURCE_URL = "https://haisou.cc/"


def haisou_settings() -> dict[str, Any]:
    raw = _merged_raw_settings()
    api_key = str(raw.get("api_key") or raw.get("apikey") or "").strip()
    platforms = _normalize_platforms(raw.get("platforms"))
    try:
        page_size = int(raw.get("page_size") or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    page_size = max(1, min(page_size, 100))
    search_in = str(raw.get("search_in") or DEFAULT_SEARCH_IN).strip().lower()
    if search_in not in {"title", "files"}:
        search_in = DEFAULT_SEARCH_IN
    enabled = truthy(raw.get("enabled"), bool(api_key))
    use_proxy = truthy(raw.get("use_proxy"), False)
    try:
        priority = int(raw.get("priority") if raw.get("priority") is not None else SOURCE_PRIORITY)
    except (TypeError, ValueError):
        priority = SOURCE_PRIORITY
    try:
        refresh_interval = int(raw.get("refresh_interval") or 30)
    except (TypeError, ValueError):
        refresh_interval = 30
    refresh_interval = max(5, refresh_interval)
    return {
        "api_key": api_key,
        "enabled": enabled,
        "platforms": platforms,
        "page_size": page_size,
        "search_in": search_in,
        "use_proxy": use_proxy,
        "priority": priority,
        "refresh_interval": refresh_interval,
        "test_query": str(raw.get("test_query") or "").strip(),
        "keywords": str(raw.get("keywords") or "").strip(),
        "quality": str(raw.get("quality") or "").strip(),
        "url": SOURCE_URL,
    }


def haisou_enabled(config: dict[str, Any] | None = None) -> bool:
    settings = config or haisou_settings()
    return bool(settings.get("enabled") and settings.get("api_key"))


def haisou_source_entry(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    settings = config or haisou_settings()
    if not haisou_enabled(settings):
        return None
    return {
        "id": SOURCE_ID,
        "name": SOURCE_NAME,
        "type": "site_plugin",
        "plugin": "haisou",
        "url": SOURCE_URL,
        "enabled": True,
        "use_proxy": bool(settings.get("use_proxy")),
        "priority": int(settings.get("priority") or SOURCE_PRIORITY),
        "refresh_interval": int(settings.get("refresh_interval") or 30),
        "test_query": settings.get("test_query") or "",
        "keywords": settings.get("keywords") or "",
        "quality": settings.get("quality") or "",
        "_builtin": True,
        "_haisou": True,
        "_request_timeout": REQUEST_TIMEOUT_SECONDS,
        "api_key": settings["api_key"],
        "platforms": list(settings["platforms"]),
        "page_size": settings["page_size"],
        "search_in": settings["search_in"],
    }


def haisou_proxy() -> str | None:
    return module_proxy("haisou")


def _merged_raw_settings() -> dict[str, Any]:
    legacy = get_setting("haisou", {})
    if not isinstance(legacy, dict):
        legacy = {}
    rss = get_setting("rss_sources", {})
    if not isinstance(rss, dict):
        rss = {}
    overrides = rss.get("builtin_sources") if isinstance(rss.get("builtin_sources"), dict) else {}
    override = overrides.get(SOURCE_ID) if isinstance(overrides.get(SOURCE_ID), dict) else {}
    return {**legacy, **override}


def _normalize_platforms(value: Any) -> list[str]:
    if value is None or value == "":
        return list(DEFAULT_PLATFORMS)
    if isinstance(value, str):
        items = [part.strip().lower() for part in value.replace("，", ",").split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        items = [str(part).strip().lower() for part in value if str(part).strip()]
    else:
        items = list(DEFAULT_PLATFORMS)
    allowed = [item for item in items if item in SUPPORTED_PLATFORMS]
    deliverable = [item for item in allowed if item == "115"]
    return deliverable or list(DEFAULT_PLATFORMS)
