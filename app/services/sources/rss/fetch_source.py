from __future__ import annotations

import time
from typing import Any

import httpx

from app.db import add_log
from app.services.source_stats import _source_stats_key, record_source_fetch, source_health_status
from app.services.link import truthy
from app.services.types import SearchResult


class RssTorznabFetchSourceMixin:
    async def _fetch_source(
        self,
        source: dict[str, Any],
        query: str | None = None,
        client: httpx.AsyncClient | None = None,
        query_context: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        name = str(source.get("name") or "订阅源").strip()
        url = self._source_url(source, query)
        if not url:
            return []
        source_key = _source_stats_key(self._source_type(source), name, str(source.get("url") or url))
        health = source_health_status(source_key)
        if health.get("degraded") and not source.get("_ignore_health"):
            add_log("warning", "rss", "订阅源暂时降级跳过", {"source": name, "reason": health.get("reason"), "source_key": source_key})
            return []
        context = _FetchContext(
            name=name,
            url=url,
            source_type=self._source_type(source),
            priority=self._source_priority(source),
            source_key=source_key,
        )
        owns_client = client is None
        active_client = client or shared_async_client(proxy=self._source_proxy(source), timeout=self._source_timeout(source), follow_redirects=True)
        try:
            results = await self._fetch_source_results(source, context, active_client, query, query_context)
            for result in results:
                result.priority = context.priority
            context.record(True, len(results))
            return results
        except Exception as exc:
            add_log("warning", "rss", "订阅源读取失败", {"source": name, "url": url, "error": str(exc)})
            context.record(False, 0, str(exc))
            return []
        finally:
            if owns_client:
                await active_client.aclose()

    def _source_timeout(self, source: dict[str, Any]) -> float:
        try:
            raw = float(source.get("_request_timeout") or source.get("timeout") or 25)
        except (TypeError, ValueError):
            return 25.0
        # Haisou official API docs require client timeout > 60s to avoid partial billing.
        if self._site_plugin_id(source) == "haisou" or truthy(source.get("_haisou")):
            return max(65.0, min(raw, 90.0))
        return max(2.0, min(raw, 30.0))

    async def _fetch_source_results(
        self,
        source: dict[str, Any],
        context: "_FetchContext",
        client: httpx.AsyncClient,
        query: str | None,
        query_context: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if context.source_type == "site_plugin":
            return await self._fetch_site_plugin_results(source, context, client, query, query_context)

        res = await client.get(context.url, headers={"User-Agent": "ToGo115/1.0"})
        res.raise_for_status()
        return self._parse_feed(source, res.text)

    async def _fetch_site_plugin_results(
        self,
        source: dict[str, Any],
        context: "_FetchContext",
        client: httpx.AsyncClient,
        query: str | None,
        query_context: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if self._site_plugin_id(source) == "haisou":
            return await self._fetch_haisou_results(source, context, query)
        res = await self._get_magnet_web_page(client, context.url)
        if self._is_magnet_web_challenge(str(res.url), res.text):
            add_log("warning", "rss", "站点插件订阅源被浏览器验证拦截", {"source": context.name, "url": context.url, "plugin": self._site_plugin_id(source)})
            context.record(False, 0, "浏览器验证拦截")
            return []
        if self._site_plugin_id(source) == "qmp4":
            results = await self._parse_qmp4_source(source, context.url, res.text, client)
        else:
            results = await self._parse_magnet_web_source(source, context.url, res.text, client, self._query_release_year(query))
        add_log("debug", "rss", f"站点插件订阅源搜索完成：{len(results)} 条", {"source": context.name, "url": context.url, "plugin": self._site_plugin_id(source), "count": len(results)})
        return results


    async def _fetch_haisou_results(
        self,
        source: dict[str, Any],
        context: "_FetchContext",
        query: str | None,
    ) -> list[SearchResult]:
        from app.services.sources.haisou import search_haisou

        if not str(query or "").strip():
            return []
        results = await search_haisou(str(query).strip(), source=source)
        add_log(
            "debug",
            "rss",
            f"haisou source search done: {len(results)}",
            {"source": context.name, "url": context.url, "plugin": "haisou", "count": len(results)},
        )
        return results


class _FetchContext:
    def __init__(self, name: str, url: str, source_type: str, priority: int, source_key: str) -> None:
        self.name = name
        self.url = url
        self.source_type = source_type
        self.priority = priority
        self.source_key = source_key
        self.started = time.perf_counter()

    def record(self, ok: bool, count: int, error: str | None = None) -> None:
        record_source_fetch(
            self.source_key,
            self.name,
            self.source_type,
            ok,
            count,
            round((time.perf_counter() - self.started) * 1000),
            error,
        )
