from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.sources.haisou.budget import (
    allow_haisou_search,
    get_cached_haisou_search,
    note_haisou_search,
    search_cache_key,
    set_cached_haisou_search,
)
from app.services.sources.haisou.client import HaisouApiError, HaisouClient
from app.services.sources.haisou.config import haisou_settings
from app.services.sources.haisou.mapper import map_haisou_items
from app.services.types import SearchResult


async def search_haisou(
    query: str,
    *,
    source: dict[str, Any] | None = None,
    api_key: str | None = None,
    platforms: list[str] | None = None,
    page_size: int | None = None,
    search_in: str | None = None,
) -> list[SearchResult]:
    settings = haisou_settings()
    source = source or {}
    key = str(api_key or source.get("api_key") or settings.get("api_key") or "").strip()
    if not key:
        add_log("debug", "haisou", "海搜未配置 API Key，跳过搜索", {"query": query})
        return []

    platform_list = platforms or source.get("platforms") or settings.get("platforms") or ["115"]
    size = page_size if page_size is not None else source.get("page_size") or settings.get("page_size") or 20
    scope = search_in or source.get("search_in") or settings.get("search_in") or "title"
    name = str(source.get("name") or "海搜 Haisou").strip()

    cache_key = search_cache_key(query, platforms=list(platform_list), page_size=int(size), search_in=str(scope))
    cached = get_cached_haisou_search(cache_key)
    if isinstance(cached, list):
        return list(cached)
    if not allow_haisou_search():
        add_log("warning", "haisou", "海搜搜索达到窗口预算，已跳过", {"query": query})
        return []

    client = HaisouClient(api_key=key)
    try:
        note_haisou_search()
        result = await client.search(
            query,
            platforms=list(platform_list),
            search_in=str(scope),
            page=1,
            page_size=int(size),
        )
    except HaisouApiError as exc:
        add_log(
            "warning",
            "haisou",
            "海搜搜索失败",
            {"query": query, "error": str(exc), "code": exc.code, "credits": exc.credits, "retryable": exc.retryable},
        )
        return []
    except Exception as exc:
        add_log("warning", "haisou", "海搜搜索异常", {"query": query, "error": str(exc)})
        return []

    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        items = []
    mapped = map_haisou_items(items, source_name=name, platforms=list(platform_list))
    add_log(
        "info",
        "haisou",
        "海搜搜索完成",
        {"query": query, "raw": len(items), "usable": len(mapped), "platforms": list(platform_list)},
    )
    return mapped