from __future__ import annotations

import asyncio
import base64
import re
from typing import Any
from urllib.parse import urljoin

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
        if self._is_seedog_url(source_url) and detail_candidates:
            for item in pages:
                if isinstance(item, Exception) or not item:
                    continue
                detail_url, detail_html = item
                seedog_results = await self._parse_seedog_detail_page(
                    client, source, detail_url, detail_html, source_url
                )
                results.extend(seedog_results)
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

    _SEEDOG_BASE64_DATA_RE = re.compile(r'const\s+data\s*=\s*"([A-Za-z0-9+/=]+)"')
    _SEEDOG_LINK_START_RE = re.compile(r'/link_start/\?seed_id=(\d+)')

    async def _parse_seedog_detail_page(
        self,
        client: httpx.AsyncClient,
        source: dict[str, Any],
        detail_url: str,
        detail_html: str,
        source_url: str,
    ) -> list[SearchResult]:
        source_name = str(source.get("name") or "Seedog").strip()
        results: list[SearchResult] = []
        for match in self._SEEDOG_LINK_START_RE.finditer(detail_html):
            seed_id = match.group(1)
            link_start_url = urljoin(detail_url, f"/link_start/?seed_id={seed_id}")
            try:
                res = await self._get_magnet_web_page(client, link_start_url, detail_url)
                ls_html = res.text
                data_match = self._SEEDOG_BASE64_DATA_RE.search(ls_html)
                if not data_match:
                    continue
                magnet_link = base64.b64decode(data_match.group(1)).decode("utf-8", errors="replace")
                if not magnet_link.startswith("magnet:?"):
                    continue
                title_match = re.search(
                    rf'<a[^>]*href="[^"]*/link_start/\?seed_id={re.escape(seed_id)}[^"]*"[^>]*title="([^"]*)"',
                    detail_html,
                )
                title = (title_match.group(1) if title_match else f"Seedog {seed_id}").strip()
                text = f"{title}\n{detail_url}"
                results.append(SearchResult(
                    title=title,
                    url=magnet_link,
                    source=f"{self._source_type(source)}:{source_name}",
                    message_id=detail_url,
                    context=text,
                ))
            except Exception as exc:
                add_log("warning", "rss", "Seedog 磁力链接获取失败", {"seed_id": seed_id, "error": str(exc)})
        return results


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
