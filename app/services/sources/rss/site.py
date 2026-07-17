from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.db import add_log
from app.services.link import BT1207_DETAIL_DELAY_SECONDS
from app.services.sources.rss.detail_candidates import RssTorznabDetailCandidateMixin
from app.services.sources.rss.qmp4 import RssTorznabQmp4Mixin
from app.services.sources.rss.site_detail import RssTorznabSiteDetailMixin
from app.services.sources.rss.site_page import RssTorznabSitePageMixin
from app.services.sources.rss.url_builder import RssTorznabUrlBuilderMixin
from app.services.sources.rss.web import RssTorznabWebMixin
from app.services.types import SearchResult


class RssTorznabSiteMixin(
    RssTorznabUrlBuilderMixin,
    RssTorznabDetailCandidateMixin,
    RssTorznabWebMixin,
    RssTorznabQmp4Mixin,
    RssTorznabSiteDetailMixin,
    RssTorznabSitePageMixin,
):
    async def _parse_magnet_web_source(
        self,
        source: dict[str, Any],
        source_url: str,
        html_text: str,
        client: httpx.AsyncClient,
        release_year: int | None = None,
    ) -> list[SearchResult]:
        results = self._parse_magnet_web_page(source, source_url, html_text)
        detail_candidates = self._magnet_web_detail_candidates(source_url, html_text, release_year)
        detail_limit = _fast_detail_limit(source)
        if detail_limit:
            detail_candidates = detail_candidates[:detail_limit]
        detail_success = 0
        if detail_candidates:
            detail_contexts = {url: context for url, context in detail_candidates}
            pages = await self._fetch_detail_pages(client, source_url, detail_candidates, source)
            for item in pages:
                if isinstance(item, Exception):
                    add_log(
                        "warning",
                        "rss",
                        "站点插件详情读取失败",
                        {"source": source.get("name") or "订阅源", "plugin": self._site_plugin_id(source), "error": str(item)},
                    )
                    continue
                if not item:
                    continue
                detail_url, detail_html = item
                detail_success += 1
                results.extend(self._parse_magnet_web_page(source, detail_url, detail_html, detail_contexts.get(detail_url, "")))
        results = self._dedupe_results(results)
        self._log_bt1207_detail_summary(source, source_url, detail_candidates, detail_success, results)
        return results

    async def _fetch_detail_pages(self, client: httpx.AsyncClient, source_url: str, detail_candidates: list[tuple[str, str]], source: dict[str, Any]) -> list[Any]:
        if self._is_bt1207_url(source_url):
            if source.get("_parallel_details"):
                return await asyncio.gather(
                    *(self._fetch_bt1207_detail_with_retry(client, url, source_url) for url, _ in detail_candidates),
                    return_exceptions=True,
                )
            pages = []
            delay = _bt1207_detail_delay(source)
            for url, _ in detail_candidates:
                pages.append(await self._fetch_bt1207_detail_with_retry(client, url, source_url))
                await asyncio.sleep(delay)
            return pages
        return await asyncio.gather(
            *(self._fetch_magnet_web_detail(client, url, source_url) for url, _ in detail_candidates),
            return_exceptions=True,
        )

    def _log_bt1207_detail_summary(
        self,
        source: dict[str, Any],
        source_url: str,
        detail_candidates: list[tuple[str, str]],
        detail_success: int,
        results: list[SearchResult],
    ) -> None:
        if not self._is_bt1207_url(source_url):
            return
        add_log(
            "debug",
            "rss",
            f"BT1207 磁力详情解析完成：详情页 {len(detail_candidates)}，成功 {detail_success}，磁力 {len(results)}",
            {"source": source.get("name") or "订阅源", "url": source_url, "candidates": len(detail_candidates), "details": detail_success, "count": len(results)},
        )


def _fast_detail_limit(source: dict[str, Any]) -> int | None:
    try:
        value = int(source.get("_fast_detail_limit") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else None


def _bt1207_detail_delay(source: dict[str, Any]) -> float:
    try:
        return max(0.0, min(2.0, float(source.get("_bt1207_detail_delay"))))
    except (TypeError, ValueError):
        return BT1207_DETAIL_DELAY_SECONDS
