from __future__ import annotations

import time
from typing import Any

import httpx

from app.services.link_parser import _html_page_title


class RssTorznabTestMixin:
    async def test_source(self, source: dict[str, Any], query: str | None = None) -> dict[str, Any]:
        name = str(source.get("name") or "订阅源").strip()
        normalized = self._normalized_test_source(source)
        query_value = query or str(source.get("name") or "").strip()
        url = self._source_url(normalized, query_value)
        if not url:
            return {"ok": False, "source": name, "error": "订阅源 URL 不能为空"}

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(proxy=self._source_proxy(normalized), timeout=25, follow_redirects=True) as client:
                url, res, results = await self._test_source_with_client(normalized, url, query_value, client, started)
            diagnostic = self._source_test_diagnostic(normalized, url, res, results, query_value)
            return self._source_test_success_payload(name, url, res, query_value, started, results, diagnostic)
        except _SourceTestFailure as exc:
            return exc.payload
        except Exception as exc:
            return {
                "ok": False,
                "source": name,
                "url": url,
                "query": query_value,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "error": str(exc),
            }

    def _normalized_test_source(self, source: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(source)
        normalized.setdefault("enabled", True)
        normalized.setdefault("type", "rss")
        return normalized

    async def _test_source_with_client(
        self,
        source: dict[str, Any],
        url: str,
        query: str,
        client: httpx.AsyncClient,
        started: float,
    ) -> tuple[str, httpx.Response | None, list]:
        if self._source_type(source) == "site_plugin":
            return await self._test_site_plugin_source(source, url, query, client, started)

        res = await client.get(url, headers={"User-Agent": "ToGo115/1.0"})
        res.raise_for_status()
        return url, res, self._parse_feed(source, res.text)

    async def _test_site_plugin_source(
        self,
        source: dict[str, Any],
        url: str,
        query: str,
        client: httpx.AsyncClient,
        started: float,
    ) -> tuple[str, httpx.Response | None, list]:
        if self._site_plugin_id(source) == "qmp4":
            return await self._test_qmp4_source(source, url, query, client, started)
        res = await self._get_magnet_web_page(client, url)
        self._raise_if_challenged(source, url, res, started)
        results = await self._parse_magnet_web_source(source, url, res.text, client, self._query_release_year(query))
        return url, res, results

    async def _test_qmp4_source(
        self,
        source: dict[str, Any],
        url: str,
        query: str,
        client: httpx.AsyncClient,
        started: float,
    ) -> tuple[str, httpx.Response | None, list]:
        res: httpx.Response | None = None
        for qmp4_query in self._source_queries(source, [query]):
            if qmp4_query is None:
                continue
            next_url = self._source_url(source, qmp4_query)
            if not next_url:
                continue
            res = await self._get_magnet_web_page(client, next_url)
            self._raise_if_challenged(source, next_url, res, started)
            results = await self._parse_qmp4_source(source, next_url, res.text, client)
            if results:
                return next_url, res, results
            url = next_url
        if res is None:
            raise ValueError("订阅源 URL 不能为空")
        return url, res, []

    def _raise_if_challenged(self, source: dict[str, Any], url: str, res: httpx.Response, started: float) -> None:
        if not self._is_magnet_web_challenge(str(res.url), res.text):
            return
        error = {
            "ok": False,
            "source": str(source.get("name") or "订阅源").strip(),
            "url": url,
            "status_code": res.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": "站点插件被浏览器验证拦截，未拿到真实搜索结果",
        }
        raise _SourceTestFailure(error)

    def _source_test_diagnostic(self, source: dict[str, Any], url: str, res: httpx.Response | None, results: list, query: str) -> dict[str, Any]:
        if self._source_type(source) != "site_plugin" or results:
            return {}
        if res is None:
            return {}
        plugin_id = self._site_plugin_id(source)
        diagnostic = {
            "message": "已成功打开搜索页，但没有从页面或详情页解析到磁力链接。",
            "final_url": str(res.url),
            "page_title": _html_page_title(res.text, ""),
            "plugin": plugin_id,
        }
        if plugin_id == "qmp4":
            candidates = self._qmp4_detail_candidates(url, res.text)
            diagnostic["detail_candidates"] = len(candidates)
            if candidates:
                diagnostic["message"] = (
                    f"已找到 {len(candidates)} 个详情候选，但详情页未解析到磁力链接。"
                )
            elif "list" not in str(res.text or ""):
                diagnostic["message"] = "QMP4 搜索接口未返回可用结果列表。"
        else:
            diagnostic["detail_candidates"] = len(
                self._magnet_web_detail_candidates(url, res.text, self._query_release_year(query))
            )
        return diagnostic

    def _source_test_success_payload(
        self,
        name: str,
        url: str,
        res: httpx.Response | None,
        query: str,
        started: float,
        results: list,
        diagnostic: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "source": name,
            "url": url,
            "final_url": str(res.url) if res is not None else url,
            "query": query,
            "status_code": res.status_code if res is not None else None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "items": len(results),
            "sample": [result.__dict__ for result in results[:5]],
            **({"diagnostic": diagnostic} if diagnostic else {}),
        }


class _SourceTestFailure(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error") or "订阅源测试失败")
        self.payload = payload

