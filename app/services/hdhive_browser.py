from __future__ import annotations

import asyncio
import base64
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.config import settings
from app.db import add_log


HDHIVE_DEFAULT_URL = "https://hdhive.com/"
_VIEWPORT = {"width": 1365, "height": 900}


class HdhiveEmbeddedBrowser:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._source: dict[str, Any] = {}
        self._base_url = HDHIVE_DEFAULT_URL
        self._user_data_dir = ""

    async def open(self, source: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._source = dict(source or {})
            self._base_url = _hdhive_base_url(self._source)
            self._user_data_dir = _hdhive_user_data_dir(self._source)
            if self._context and self._page:
                return await self._snapshot_locked("HDHive embedded browser is already running")
            await self._start_locked()
            await self._page.goto(self._base_url, wait_until="domcontentloaded", timeout=_hdhive_timeout_ms(self._source))
            await _settle_page(self._page)
            add_log("info", "rss", "HDHive embedded browser opened", {"url": self._base_url, "user_data_dir": self._user_data_dir})
            return await self._snapshot_locked("HDHive embedded browser opened")

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return await self._snapshot_locked()

    async def click(self, x: float, y: float) -> dict[str, Any]:
        async with self._lock:
            page = self._require_page()
            await page.mouse.click(float(x), float(y))
            await self._activate_latest_page()
            await _settle_page(self._page)
            return await self._snapshot_locked()

    async def type_text(self, text: str) -> dict[str, Any]:
        async with self._lock:
            page = self._require_page()
            await page.keyboard.type(str(text or ""), delay=15)
            await _settle_page(page)
            return await self._snapshot_locked()

    async def press_key(self, key: str) -> dict[str, Any]:
        async with self._lock:
            page = self._require_page()
            await page.keyboard.press(str(key or "Enter"))
            await self._activate_latest_page()
            await _settle_page(self._page)
            return await self._snapshot_locked()

    async def navigate(self, url: str | None = None) -> dict[str, Any]:
        async with self._lock:
            page = self._require_page()
            target = _hdhive_absolute_url(self._base_url, url)
            await page.goto(target, wait_until="domcontentloaded", timeout=_hdhive_timeout_ms(self._source))
            await _settle_page(page)
            return await self._snapshot_locked()

    async def close(self) -> dict[str, Any]:
        async with self._lock:
            await self._close_locked()
            add_log("info", "rss", "HDHive embedded browser closed", {})
            return {"ok": True, "running": False}

    async def _start_locked(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            add_log("warning", "rss", "HDHive browser dependency is unavailable", {"error": str(exc)})
            raise
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            executable_path=_hdhive_executable_path(self._source),
            headless=_hdhive_embedded_headless(self._source),
            locale="zh-CN",
            viewport=_VIEWPORT,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context.on("page", lambda page: setattr(self, "_page", page))
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def _activate_latest_page(self) -> None:
        if not self._context:
            return
        pages = [page for page in self._context.pages if not page.is_closed()]
        if pages:
            self._page = pages[-1]

    async def _snapshot_locked(self, message: str = "") -> dict[str, Any]:
        page = self._require_page()
        await self._activate_latest_page()
        page = self._require_page()
        screenshot = await page.screenshot(type="png", full_page=False)
        title = ""
        with _suppress_playwright_errors():
            title = await page.title()
        return {
            "ok": True,
            "running": True,
            "message": message,
            "url": page.url,
            "title": title,
            "width": _VIEWPORT["width"],
            "height": _VIEWPORT["height"],
            "user_data_dir": self._user_data_dir,
            "screenshot": f"data:image/png;base64,{base64.b64encode(screenshot).decode('ascii')}",
        }

    def _require_page(self) -> Any:
        if not self._context or not self._page or self._page.is_closed():
            raise RuntimeError("HDHive embedded browser is not running")
        return self._page

    async def _close_locked(self) -> None:
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._playwright = None
        self._page = None


class _suppress_playwright_errors:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return exc is not None


hdhive_embedded_browser = HdhiveEmbeddedBrowser()


async def open_hdhive_embedded_browser(source: dict[str, Any]) -> dict[str, Any]:
    return await hdhive_embedded_browser.open(source)


async def hdhive_browser_snapshot() -> dict[str, Any]:
    return await hdhive_embedded_browser.snapshot()


async def hdhive_browser_click(x: float, y: float) -> dict[str, Any]:
    return await hdhive_embedded_browser.click(x, y)


async def hdhive_browser_type(text: str) -> dict[str, Any]:
    return await hdhive_embedded_browser.type_text(text)


async def hdhive_browser_key(key: str) -> dict[str, Any]:
    return await hdhive_embedded_browser.press_key(key)


async def hdhive_browser_navigate(url: str | None = None) -> dict[str, Any]:
    return await hdhive_embedded_browser.navigate(url)


async def hdhive_browser_close() -> dict[str, Any]:
    return await hdhive_embedded_browser.close()


def _hdhive_base_url(source: dict[str, Any]) -> str:
    return (str(source.get("url") or HDHIVE_DEFAULT_URL).strip() or HDHIVE_DEFAULT_URL).rstrip("/") + "/"


def _hdhive_user_data_dir(source: dict[str, Any]) -> str:
    configured = str(source.get("browser_user_data_dir") or os.getenv("TOGO115_HDHIVE_USER_DATA_DIR") or "").strip()
    if configured:
        return configured
    return str(settings.data_dir / "hdhive-browser")


def _hdhive_executable_path(source: dict[str, Any]) -> str | None:
    configured = str(source.get("browser_path") or os.getenv("TOGO115_HDHIVE_BROWSER_PATH") or os.getenv("TOGO115_CHROMIUM_PATH") or "").strip()
    if configured:
        return configured
    for candidate in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _hdhive_embedded_headless(source: dict[str, Any]) -> bool:
    value = str(source.get("embedded_headless") if "embedded_headless" in source else os.getenv("TOGO115_HDHIVE_EMBEDDED_HEADLESS", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _hdhive_timeout_ms(source: dict[str, Any]) -> int:
    try:
        return max(8000, min(int(float(source.get("browser_timeout") or 20000)), 60000))
    except (TypeError, ValueError):
        return 20000


def _hdhive_absolute_url(base_url: str, url: str | None) -> str:
    value = str(url or "").strip()
    return urljoin(base_url, value or base_url)


async def _settle_page(page: Any) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        await asyncio.sleep(0.3)
