from __future__ import annotations

import asyncio
import base64
import os
import re
import signal
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from app.config import settings
from app.db import add_log
from app.services.integration_state import get_setting


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
        self._proxy: dict[str, str] | None = None

    async def open(self, source: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._source = dict(source or {})
            self._base_url = _hdhive_base_url(self._source)
            self._user_data_dir = _hdhive_user_data_dir(self._source)
            self._proxy = hdhive_playwright_proxy(self._source)
            if self._context and self._page:
                return await self._snapshot_locked("HDHive embedded browser is already running")
            try:
                await self._start_locked()
            except Exception as exc:
                await self._close_locked()
                message = _hdhive_browser_error_message(exc)
                proxy_label = hdhive_proxy_label(self._source)
                add_log("warning", "rss", "HDHive embedded browser failed", {"error": message, "error_type": type(exc).__name__, "user_data_dir": self._user_data_dir, "proxy_enabled": bool(proxy_label), "proxy_server": proxy_label})
                return {"ok": False, "running": False, "error": message, "error_type": type(exc).__name__, "user_data_dir": self._user_data_dir, "proxy_enabled": bool(proxy_label), "proxy_server": proxy_label}
            await self._goto_start_page()
            snapshot = await self._snapshot_locked("HDHive embedded browser opened")
            add_log(
                "info",
                "rss",
                "HDHive embedded browser opened",
                {
                    "url": self._base_url,
                    "page_url": snapshot.get("url"),
                    "title": snapshot.get("title"),
                    "diagnostic": snapshot.get("diagnostic"),
                    "user_data_dir": self._user_data_dir,
                    "proxy_enabled": snapshot.get("proxy_enabled"),
                    "proxy_server": snapshot.get("proxy_server"),
                },
            )
            return snapshot

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
        _release_hdhive_profile_lock(self._user_data_dir)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            executable_path=_hdhive_executable_path(self._source),
            headless=_hdhive_embedded_headless(self._source),
            locale="zh-CN",
            viewport=_VIEWPORT,
            proxy=self._proxy,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context.on("page", lambda page: setattr(self, "_page", page))
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def _goto_start_page(self) -> None:
        page = self._require_page()
        try:
            await page.goto(self._base_url, wait_until="domcontentloaded", timeout=_hdhive_timeout_ms(self._source))
            await _settle_page(page)
        except Exception as exc:
            add_log("warning", "rss", "HDHive embedded browser navigation failed", {"url": self._base_url, "error": _compact_hdhive_browser_error(exc), "error_type": type(exc).__name__})

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
        page_text = ""
        with _suppress_playwright_errors():
            page_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        diagnostic = _hdhive_page_diagnostic(page.url, title, page_text, bool(self._proxy))
        proxy_label = _proxy_label(self._proxy)
        return {
            "ok": True,
            "running": True,
            "message": message,
            "url": page.url,
            "title": title,
            "diagnostic": diagnostic,
            "page_text_excerpt": _compact_text(page_text, 320),
            "proxy_enabled": bool(self._proxy),
            "proxy_server": proxy_label,
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
        self._proxy = None


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


def hdhive_playwright_proxy(source: dict[str, Any]) -> dict[str, str] | None:
    if not _truthy(source.get("use_proxy")):
        return None
    proxy_url = str(source.get("proxy_url") or get_setting("proxy").get("url") or "").strip()
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}"
    if parsed.port:
        server = f"{server}:{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def hdhive_proxy_label(source: dict[str, Any]) -> str:
    return _proxy_label(hdhive_playwright_proxy(source))


def _proxy_label(proxy: dict[str, str] | None) -> str:
    if not proxy:
        return ""
    return str(proxy.get("server") or "").strip()


def _hdhive_timeout_ms(source: dict[str, Any]) -> int:
    try:
        return max(8000, min(int(float(source.get("browser_timeout") or 20000)), 60000))
    except (TypeError, ValueError):
        return 20000


def _hdhive_absolute_url(base_url: str, url: str | None) -> str:
    value = str(url or "").strip()
    return urljoin(base_url, value or base_url)


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _hdhive_page_diagnostic(url: str, title: str, page_text: str, proxy_enabled: bool) -> str:
    text = f"{title}\n{page_text}".strip()
    lowered = text.lower()
    if "出现了很多奇怪的错误" in text or "请联系管理员处理" in text:
        proxy_hint = "当前已启用代理，建议更换代理出口后重新打开。" if proxy_enabled else "当前未启用代理，建议在影巢订阅源里启用代理后重试。"
        return f"影巢返回站内错误页，页面已经加载但站点拒绝继续处理。{proxy_hint}"
    if "sorry, you have been blocked" in lowered or "attention required" in lowered or "cloudflare" in lowered:
        proxy_hint = "当前代理出口可能被 Cloudflare 风控。" if proxy_enabled else "当前直连访问可能被 Cloudflare 风控。"
        return f"影巢访问被站点防护拦截。{proxy_hint}"
    if not page_text.strip():
        return "页面正文为空，可能仍在加载、脚本执行失败，或被浏览器/网络层拦截。"
    if "登录" in page_text and ("telegram" in lowered or "tg" in lowered):
        return "影巢登录页已打开，请在内置浏览器中完成 Telegram 登录。"
    if "hdhive" in lowered and url:
        return "影巢页面已打开。"
    return ""


def _compact_text(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else f"{value[:limit]}..."


async def _settle_page(page: Any) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        await asyncio.sleep(0.3)


def _release_hdhive_profile_lock(user_data_dir: str) -> None:
    lock_pid = _hdhive_profile_lock_pid(user_data_dir)
    if lock_pid and _process_is_alive(lock_pid):
        if _process_looks_like_browser(lock_pid):
            _terminate_process(lock_pid)
        if _process_is_alive(lock_pid):
            raise RuntimeError(f"HDHive browser profile is still in use by process {lock_pid}. Close the old browser and try again.")
    removed = False
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = Path(user_data_dir) / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
                removed = True
        except OSError:
            pass
    if removed:
        add_log("info", "rss", "HDHive embedded browser profile lock cleared", {"user_data_dir": user_data_dir, "pid": lock_pid})


def _hdhive_profile_lock_pid(user_data_dir: str) -> int | None:
    lock_path = Path(user_data_dir) / "SingletonLock"
    try:
        values = [os.readlink(lock_path)] if lock_path.is_symlink() else [lock_path.read_text(encoding="utf-8", errors="ignore")]
    except OSError:
        return None
    for value in values:
        match = re.search(r"(?:^|-)(\d+)$", str(value).strip())
        if match:
            return int(match.group(1))
    return None


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    proc_path = Path("/proc") / str(pid)
    if proc_path.exists():
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _process_looks_like_browser(pid: int) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_text(encoding="utf-8", errors="ignore").replace("\x00", " ").lower()
    except OSError:
        return True
    return any(marker in command for marker in ("chromium", "chrome", "msedge"))


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(30):
        if not _process_is_alive(pid):
            return
        try:
            import time

            time.sleep(0.1)
        except Exception:
            return


def _hdhive_browser_error_message(exc: Exception) -> str:
    message = _compact_hdhive_browser_error(exc)
    if "profile appears to be in use" in message.lower() or "processsingleton" in message.lower() or "locked the profile" in message.lower():
        return "影巢浏览器用户目录仍被旧 Chromium 占用，请关闭旧登录浏览器后重试。"
    if "no module named 'playwright'" in message.lower():
        return "镜像内缺少 Playwright 依赖，请拉取最新 main 镜像后重建容器。"
    if "executable" in message.lower() and "doesn't exist" in message.lower():
        return "镜像内 Chromium 路径不可用，请清空浏览器路径或确认 TOGO115_CHROMIUM_PATH。"
    return message


def _compact_hdhive_browser_error(exc: Exception, limit: int = 800) -> str:
    message = str(exc).strip() or type(exc).__name__
    return message if len(message) <= limit else f"{message[:limit]}..."
