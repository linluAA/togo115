from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.db import add_log, db
import app.services.subscription.runtime as runtime
from app.services.adapters.telegram import TelegramClientAdapter
from app.services.link_downloads import is_valid_download_link
from app.services.sources.rss_torznab import RssTorznabAdapter, SearchResult
from app.services.subscription.match.matching import _extra_search_keywords, _result_debug_payload
from app.services.subscription.resource.ops import (
    _existing_resource_rows,
    _fallback_blocked_by_primary_resource,
    _matching_results,
    _resource_already_exists,
    _subscription_115_resources,
)


async def search_telegram_history(
    facade: Any,
    subscription: dict,
    search_title: str,
    *,
    incremental: bool = False,
    fast: bool = False,
) -> list[SearchResult]:
    """Search Telegram history and convert transport errors into observable logs."""
    subscription_id = int(subscription["id"])
    timeout = 6 if fast and not incremental else runtime.TELEGRAM_SEARCH_TIMEOUT_SECONDS
    try:
        results = await asyncio.wait_for(
            _telegram_search_call(subscription, search_title, incremental=incremental, fast=fast),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        add_log(
            "warning",
            "subscription",
            "Telegram 快速搜索超时，继续尝试完整搜索/订阅源" if fast else "Telegram 历史搜索超时，继续尝试订阅源/磁力",
            {"id": subscription_id, "title": search_title, "timeout": timeout},
        )
        return []
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "Telegram 快速搜索异常，继续尝试完整搜索/订阅源" if fast else "Telegram 历史搜索异常，继续尝试订阅源/磁力",
            {"id": subscription_id, "title": search_title, "error": str(exc)},
        )
        return []

    if results:
        add_log(
            "info",
            "subscription",
            "TG 快速搜索已提取到资源链接" if fast else "TG 历史搜索已提取到资源链接",
            {"id": subscription_id, "title": search_title, "count": len(results)},
        )
    return results


def _telegram_search_call(subscription: dict, search_title: str, *, incremental: bool, fast: bool):
    adapter = TelegramClientAdapter()
    keywords = _extra_search_keywords(subscription)
    if fast and not incremental:
        return adapter.search_history_fast(search_title, keywords)
    return adapter.search_history(search_title, keywords, incremental=incremental)


def fallback_usable_checker(facade: Any, subscription: dict) -> Callable[[SearchResult], bool]:
    """Build a predicate used by subscription sources to stop at the first usable hit."""
    subscription_id = int(subscription["id"])
    existing_rows: list[dict[str, Any]] | None = None
    existing_115: list[dict[str, Any]] | None = None

    def is_usable(result: SearchResult) -> bool:
        nonlocal existing_rows, existing_115
        try:
            if not is_valid_download_link(getattr(result, "url", "")):
                return False
            if not _matching_results(subscription, [result]):
                return False
            with db() as conn:
                if existing_rows is None:
                    existing_rows = _existing_resource_rows(conn, subscription_id)
                if existing_115 is None:
                    existing_115 = _subscription_115_resources(conn, subscription_id)
                if _fallback_blocked_by_primary_resource(conn, subscription, result, existing_115):
                    return False
                return _resource_already_exists(conn, subscription_id, result, subscription, existing_rows) is None
        except Exception as exc:
            add_log(
                "warning",
                "subscription",
                "订阅源/磁力结果可用性判断异常，已跳过单条结果",
                {"id": subscription_id, **_result_debug_payload(result), "error": str(exc)},
            )
            return False

    return is_usable


async def search_fallback_sources(
    facade: Any,
    subscription: dict,
    search_title: str,
) -> list[dict[str, Any]]:
    """Search RSS/Torznab/site-plugin sources after Telegram has no new usable hit."""
    subscription_id = int(subscription["id"])
    try:
        return await asyncio.wait_for(
            RssTorznabAdapter().search_history_by_priority_until_match(
                search_title,
                _extra_search_keywords(subscription),
                fallback_usable_checker(facade, subscription),
                query_context=_rss_query_context(subscription),
            ),
            timeout=runtime.RSS_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        add_log(
            "warning",
            "subscription",
            "订阅源/磁力搜索超时",
            {"id": subscription_id, "title": search_title, "timeout": runtime.RSS_SEARCH_TIMEOUT_SECONDS},
        )
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "订阅源/磁力搜索异常",
            {"id": subscription_id, "title": search_title, "error": str(exc)},
        )
    return []


def _rss_query_context(subscription: dict) -> dict[str, Any]:
    return {
        "title": subscription.get("title"),
        "media_type": subscription.get("media_type"),
        "tmdb_id": subscription.get("tmdb_id"),
        "release_year": subscription.get("release_year"),
    }
