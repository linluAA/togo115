from __future__ import annotations

import asyncio

import httpx

from app.db import add_log
from app.services.link import BT1207_DETAIL_DELAY_SECONDS, BT1207_DETAIL_RETRIES


class RssTorznabSiteDetailMixin:
    async def _fetch_magnet_web_detail(self, client: httpx.AsyncClient, url: str, referer: str | None = None) -> tuple[str, str]:
        res = await self._get_magnet_web_page(client, url, referer)
        return url, res.text

    async def _fetch_bt1207_detail_with_retry(self, client: httpx.AsyncClient, url: str, referer: str | None = None) -> tuple[str, str] | Exception | None:
        last_error: Exception | None = None
        for attempt in range(1, BT1207_DETAIL_RETRIES + 1):
            try:
                return await self._fetch_magnet_web_detail(client, url, referer)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in (429, 503):
                    return exc
                await self._solve_bt1207_challenge(client, url)
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(BT1207_DETAIL_DELAY_SECONDS * attempt)
        if last_error:
            add_log("warning", "rss", "BT1207 详情页多次读取失败", {"url": url, "error": str(last_error)})
        return last_error
