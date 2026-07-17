from __future__ import annotations

import asyncio
import secrets
import time
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.db import add_log
from app.services.link import (
    BT1207_DETAIL_DELAY_SECONDS,
    BT1207_DETAIL_RETRIES,
    _html_page_title,
)


class RssTorznabWebMixin:
    def _is_bt1207_url(self, url: str | None) -> bool:
        host = urlparse(str(url or "")).netloc.lower()
        return "bt1207" in host

    def _is_qmp4_url(self, url: str | None) -> bool:
        host = urlparse(str(url or "")).netloc.lower()
        return "qmp4.com" in host

    def _is_bt1207_search_url(self, url: str | None) -> bool:
        parsed = urlparse(str(url or ""))
        if "bt1207" not in parsed.netloc.lower():
            return False
        return parsed.path.rstrip("/") == "/search" and bool(parsed.query)

    def _magnet_web_headers(self, referer: str | None = None, ajax: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": self.MAGNET_WEB_BROWSER_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if ajax:
            headers.update(
                {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        else:
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        if referer:
            headers["Referer"] = referer
        return headers

    def _is_magnet_web_challenge(self, url: str, html_text: str) -> bool:
        lowered_url = str(url or "").lower()
        lowered_html = str(html_text or "").lower()
        return (
            "/recaptcha/" in lowered_url
            or "recaptcha - bot challenge" in lowered_html
            or "/anti/recaptcha/v4/verify" in lowered_html
            or "checking your browser before accessing" in lowered_html
            or ("系统安全验证" in str(html_text or "") and "verify_check?type=search" in lowered_html)
        )

    def _is_bt1207_search_home_fallback(self, requested_url: str, response_url: str, html_text: str) -> bool:
        if not self._is_bt1207_search_url(requested_url):
            return False
        return self._is_bt1207_home_fallback(requested_url, response_url, html_text)

    def _is_bt1207_home_fallback(self, requested_url: str, response_url: str, html_text: str) -> bool:
        if not self._is_bt1207_url(requested_url):
            return False
        requested = urlparse(str(requested_url or ""))
        requested_path = requested.path.rstrip("/") or "/"
        if requested_path == "/":
            return False
        final = urlparse(str(response_url or ""))
        final_path = final.path.rstrip("/") or "/"
        if final_path == requested_path:
            return False
        title = _html_page_title(html_text or "", "")
        return final_path == "/" or title == "BT1207 - 好用的磁力链接搜索引擎"

    async def _solve_bt1207_challenge(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        challenge_url = urljoin(origin, "/recaptcha/v4/challenge?url=" + quote(origin, safe=":/") + "&s=1")
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        uid = "".join(secrets.choice(alphabet) for _ in range(10)) + "_" + time.strftime("%Y%m%d%H%M%S")
        client.cookies.set("aywcUid", uid, domain=parsed.hostname or parsed.netloc, path="/")
        client.cookies.set("aywcUid", uid, path="/")
        challenge_res = await client.get(challenge_url, headers=self._magnet_web_headers(origin + "/"))
        challenge_res.raise_for_status()
        gen_res = await client.get(
            urljoin(origin, "/anti/recaptcha/v4/gen"),
            params={"aywcUid": uid, "_": str(int(time.time() * 1000))},
            headers=self._magnet_web_headers(challenge_url, ajax=True),
        )
        gen_res.raise_for_status()
        try:
            token = str((gen_res.json() or {}).get("token") or "")
        except ValueError:
            token = ""
        if not token:
            return False
        await asyncio.sleep(1.0)
        verify_res = await client.get(
            urljoin(origin, "/anti/recaptcha/v4/verify"),
            params={"token": token, "aywcUid": uid, "costtime": "1500"},
            headers=self._magnet_web_headers(challenge_url),
        )
        verify_res.raise_for_status()
        return True

    async def _get_magnet_web_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        referer: str | None = None,
    ) -> httpx.Response:
        request_referer = referer
        if self._is_bt1207_search_url(url):
            await self._solve_bt1207_challenge(client, url)
            parsed = urlparse(url)
            request_referer = request_referer or f"{parsed.scheme}://{parsed.netloc}/"
        res = await client.get(url, headers=self._magnet_web_headers(request_referer))
        res.raise_for_status()
        challenged = self._is_magnet_web_challenge(str(res.url), res.text)
        home_fallback = self._is_bt1207_home_fallback(url, str(res.url), res.text)
        if self._is_bt1207_url(url) and (challenged or home_fallback):
            if home_fallback:
                add_log("debug", "rss", "BT1207 页面被打回首页，重新验证后重试", {"url": url, "final_url": str(res.url)})
            if await self._solve_bt1207_challenge(client, url):
                res = await client.get(url, headers=self._magnet_web_headers(request_referer))
                res.raise_for_status()
                if self._is_bt1207_home_fallback(url, str(res.url), res.text):
                    add_log("warning", "rss", "BT1207 页面重试后仍返回首页", {"url": url, "final_url": str(res.url), "title": _html_page_title(res.text, "")})
                    if not self._is_bt1207_search_url(url):
                        raise RuntimeError("BT1207 detail page returned home page")
        return res
