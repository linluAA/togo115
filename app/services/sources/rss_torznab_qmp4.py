from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

from app.db import add_log, json_loads
from app.services.link_parser import MAGNET_WEB_DETAIL_LIMIT
from app.services.types import SearchResult


class RssTorznabQmp4Mixin:
    def _qmp4_detail_candidates(self, source_url: str, json_text: str, limit: int = MAGNET_WEB_DETAIL_LIMIT) -> list[tuple[str, str]]:
        payload = json_loads(json_text, {})
        items = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        parsed = urlparse(source_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            media_id = str(item.get("id") or "").strip()
            if not media_id:
                continue
            detail_url = urljoin(origin + "/", f"mv/{media_id}.html")
            if detail_url in seen:
                continue
            seen.add(detail_url)
            context = "\n".join(
                str(part).strip()
                for part in (item.get("name"), item.get("en"))
                if str(part or "").strip()
            )
            candidates.append((detail_url, context))
            if len(candidates) >= limit:
                break
        return candidates

    async def _parse_qmp4_source(
        self,
        source: dict[str, Any],
        source_url: str,
        json_text: str,
        client: httpx.AsyncClient,
    ) -> list[SearchResult]:
        detail_candidates = self._qmp4_detail_candidates(source_url, json_text, _qmp4_detail_limit(source))
        if not detail_candidates:
            add_log("debug", "rss", "QMP4 搜索接口未返回可用详情页", {"source": source.get("name") or "订阅源", "url": source_url})
            return []
        detail_contexts = {url: context for url, context in detail_candidates}
        pages = await asyncio.gather(
            *(self._fetch_magnet_web_detail(client, url, source_url) for url, _ in detail_candidates),
            return_exceptions=True,
        )
        results: list[SearchResult] = []
        detail_success = 0
        for item in pages:
            if isinstance(item, Exception):
                add_log("warning", "rss", "QMP4 详情读取失败", {"source": source.get("name") or "订阅源", "error": str(item)})
                continue
            if not item:
                continue
            detail_url, detail_html = item
            detail_success += 1
            results.extend(self._parse_magnet_web_page(source, detail_url, detail_html, detail_contexts.get(detail_url, "")))
        results = self._dedupe_results(results)
        add_log(
            "debug",
            "rss",
            f"QMP4 站点插件解析完成：详情页 {len(detail_candidates)}，成功 {detail_success}，磁力 {len(results)}",
            {"source": source.get("name") or "订阅源", "url": source_url, "candidates": len(detail_candidates), "details": detail_success, "count": len(results)},
        )
        return results


def _qmp4_detail_limit(source: dict[str, Any]) -> int:
    try:
        value = int(source.get("_fast_detail_limit") or 0)
    except (TypeError, ValueError):
        value = 0
    return max(1, min(value or MAGNET_WEB_DETAIL_LIMIT, MAGNET_WEB_DETAIL_LIMIT))

