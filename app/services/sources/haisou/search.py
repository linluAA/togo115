from __future__ import annotations

import asyncio
from typing import Any

from app.db import add_log
from app.services.sources.haisou.budget import (
    acquire_haisou_search_slot,
    allow_haisou_search,
    get_cached_haisou_search,
    search_cache_key,
    set_cached_haisou_search,
)
from app.services.sources.haisou.client import HaisouApiError, HaisouClient
from app.services.sources.haisou.config import haisou_settings
from app.services.sources.haisou.mapper import map_haisou_items
from app.services.types import SearchResult


MAX_SEARCH_PAGES = 3
# Per-search timeout independent of the global subscription search timeout.
# 3 pages × 20s headroom = 60s, leaving room for the 75s client timeout.
_HAISOU_SEARCH_TIMEOUT = 60.0
# Retry once for retryable errors (network blips, transient server errors).
_HAISOU_SEARCH_RETRIES = 1


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
    items: list[Any] = []
    last_error: str | None = None

    for attempt in range(1 + _HAISOU_SEARCH_RETRIES):
        if attempt > 0:
            add_log("info", "haisou", "海搜搜索重试", {"query": query, "attempt": attempt + 1})
        try:
            items = await asyncio.wait_for(
                _search_haisou_pages(client, query, platform_list, size, scope),
                timeout=_HAISOU_SEARCH_TIMEOUT,
            )
            last_error = None
            break
        except asyncio.TimeoutError:
            last_error = "海搜搜索超时"
            add_log("warning", "haisou", last_error, {"query": query, "attempt": attempt + 1})
            if attempt >= _HAISOU_SEARCH_RETRIES:
                break
        except HaisouApiError as exc:
            last_error = str(exc)
            add_log(
                "warning",
                "haisou",
                "海搜搜索失败",
                {"query": query, "error": str(exc), "code": exc.code, "credits": exc.credits, "retryable": exc.retryable},
            )
            # Only retry retryable errors; non-retryable (e.g. invalid key, consumed credits) abort immediately.
            if not exc.retryable or attempt >= _HAISOU_SEARCH_RETRIES:
                break
            await asyncio.sleep(1.0)
        except Exception as exc:
            last_error = str(exc)
            add_log("warning", "haisou", "海搜搜索异常", {"query": query, "error": str(exc)})
            if attempt >= _HAISOU_SEARCH_RETRIES:
                break
            await asyncio.sleep(1.0)

    if last_error and not items:
        return []
    mapped = map_haisou_items(items, source_name=name, platforms=list(platform_list))
    set_cached_haisou_search(cache_key, mapped)
    add_log(
        "info",
        "haisou",
        "海搜搜索完成",
        {"query": query, "raw": len(items), "usable": len(mapped), "platforms": list(platform_list)},
    )
    return mapped


async def _search_haisou_pages(
    client: HaisouClient,
    query: str,
    platform_list: list[str],
    size: int,
    scope: str,
) -> list[Any]:
    """Search haisou across multiple pages, consuming budget atomically per page."""
    items: list[Any] = []
    for page in range(1, MAX_SEARCH_PAGES + 1):
        if not acquire_haisou_search_slot():
            add_log("warning", "haisou", "海搜分页达到窗口预算，返回已获取结果", {"query": query, "page": page, "items": len(items)})
            break
        result = await client.search(
            query,
            platforms=list(platform_list),
            search_in=str(scope),
            page=page,
            page_size=int(size),
        )
        page_items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(page_items, list):
            page_items = []
        items.extend(page_items)
        if len(page_items) < int(size):
            break
    return items
