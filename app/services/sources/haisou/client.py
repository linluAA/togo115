from __future__ import annotations

from typing import Any

import httpx

from app.db import add_log
from app.services.http_client import shared_async_client
from app.services.sources.haisou.config import REQUEST_TIMEOUT_SECONDS, haisou_proxy, haisou_settings


class HaisouApiError(Exception):
    def __init__(self, message: str, *, code: int | None = None, credits: float | int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.credits = credits
        self.retryable = retryable


class HaisouClient:
    SEARCH_URL = "https://apiok.us/api/b9d1/search"
    VALIDATE_URL = "https://apiok.us/api/b9d1/validate"

    def __init__(self, api_key: str | None = None, *, timeout: float = REQUEST_TIMEOUT_SECONDS, proxy: str | None = None) -> None:
        settings = haisou_settings()
        self.api_key = str(api_key or settings.get("api_key") or "").strip()
        self.timeout = float(timeout)
        self.proxy = proxy if proxy is not None else haisou_proxy()

    async def search(
        self,
        query: str,
        *,
        platforms: list[str] | None = None,
        search_in: str = "title",
        page: int = 1,
        page_size: int = 20,
        min_size: int = 0,
        max_size: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": str(query or "").strip()[:100],
            "searchIn": search_in if search_in in {"title", "files"} else "title",
            "page": max(1, int(page or 1)),
            "pageSize": max(1, min(int(page_size or 20), 100)),
        }
        if platforms:
            body["platforms"] = list(platforms)
        if min_size:
            body["minSize"] = int(min_size)
        if max_size:
            body["maxSize"] = int(max_size)
        return await self._post(self.SEARCH_URL, body)

    async def validate(self, url: str, pwd: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"url": str(url or "").strip()}
        if pwd:
            body["pwd"] = str(pwd).strip()
        return await self._post(self.VALIDATE_URL, body)

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise HaisouApiError("海搜 API Key 未配置", code=1004, retryable=False)
        if not body.get("query") and "url" not in body:
            raise HaisouApiError("搜索关键词不能为空", code=1001, retryable=False)

        client = shared_async_client(proxy=self.proxy, timeout=self.timeout, follow_redirects=True)
        try:
            response = await client.post(url, params={"apikey": self.api_key}, json=body)
        except httpx.TimeoutException as exc:
            raise HaisouApiError(f"海搜请求超时: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise HaisouApiError(f"海搜网络错误: {exc}", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HaisouApiError(f"海搜返回非 JSON: HTTP {response.status_code}", retryable=True) from exc
        if not isinstance(payload, dict):
            raise HaisouApiError("海搜返回格式错误", retryable=True)

        code = payload.get("code")
        credits = payload.get("credits")
        try:
            code_int = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_int = None

        if code_int == 0:
            result = payload.get("result")
            return result if isinstance(result, dict) else {}

        message = str(payload.get("msg") or payload.get("tip") or f"海搜请求失败 code={code_int}")
        retryable = code_int in {1000, 1003}
        try:
            consumed = float(credits or 0)
        except (TypeError, ValueError):
            consumed = 0.0
        if consumed > 0:
            retryable = False
        add_log(
            "warning",
            "haisou",
            "海搜 API 返回错误",
            {"code": code_int, "credits": credits, "msg": message, "url": url},
        )
        raise HaisouApiError(message, code=code_int, credits=credits, retryable=retryable)