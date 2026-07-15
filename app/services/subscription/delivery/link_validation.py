from __future__ import annotations

import asyncio

from app.db import add_log
from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_AVAILABLE, SHARE_UNAVAILABLE, SHARE_UNKNOWN, Pan115Adapter
from app.services.sources.rss_torznab import SearchResult

PAN115_VALIDATION_CONCURRENCY = 4


async def filter_available_115_results(results: list[SearchResult]) -> list[SearchResult]:
    """Drop expired 115 share links before saving or delivering resources."""
    filtered, _, _ = await classify_115_results(results)
    return filtered


async def classify_115_results(results: list[SearchResult]) -> tuple[list[SearchResult], list[SearchResult], dict[str, int]]:
    """Split results into immediately usable results and 115 links that need recheck."""
    report = {"checked_115": 0, "expired_115": 0, "recheck_115": 0}
    if not results:
        return [], [], report

    adapter = Pan115Adapter()
    checked = await _check_115_links(adapter, results)
    report["checked_115"] = len(checked)
    filtered: list[SearchResult] = []
    recheck: list[SearchResult] = []

    for result in results:
        url = str(getattr(result, "url", "") or "")
        if not PAN115_URL_RE.match(url):
            filtered.append(result)
            continue

        state = checked[url]
        if state == SHARE_AVAILABLE:
            filtered.append(result)
            continue

        if state == SHARE_UNKNOWN:
            report["recheck_115"] += 1
            recheck.append(result)
            filtered.append(result)
            add_log(
                "warning",
                "subscription",
                "115 分享链接有效性待复检，先继续投递",
                {"url": url, "title": str(getattr(result, "title", "") or "")[:120], "source": getattr(result, "source", "")},
            )
            continue

        if state == SHARE_UNAVAILABLE:
            report["expired_115"] += 1
        add_log(
            "info",
            "subscription",
            "115 分享链接已失效，跳过保存和投递",
            {"url": url, "title": str(getattr(result, "title", "") or "")[:120], "source": getattr(result, "source", "")},
        )

    return filtered, recheck, report


async def _check_115_links(adapter: Pan115Adapter, results: list[SearchResult]) -> dict[str, str]:
    urls = _unique_115_urls(results)
    if not urls:
        return {}
    semaphore = asyncio.Semaphore(PAN115_VALIDATION_CONCURRENCY)

    async def check(url: str) -> tuple[str, str]:
        async with semaphore:
            return url, await adapter.share_availability(url)

    pairs = await asyncio.gather(*(check(url) for url in urls))
    return dict(pairs)


def _unique_115_urls(results: list[SearchResult]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for result in results:
        url = str(getattr(result, "url", "") or "")
        if not PAN115_URL_RE.match(url) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls
