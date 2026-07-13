from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from app.config import settings
from app.db import add_log
from app.services.link_downloads import extract_115_links, is_115_share_link
from app.services.types import SearchResult


HDHIVE_DEFAULT_URL = "https://hdhive.com/"
HDHIVE_LINK_RE = re.compile(r"/(?:movie|tv)/[A-Za-z0-9_-]+$")
HDHIVE_RESOURCE_RE = re.compile(r"/resource/115/[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class HdhiveResourceCandidate:
    title: str
    href: str
    context: str
    points: int
    unlocked: bool
    unavailable: bool

    @property
    def is_free_or_unlocked(self) -> bool:
        return self.unlocked or self.points <= 0


class RssTorznabHdhiveMixin:
    def _is_hdhive_url(self, url: str | None) -> bool:
        host = urlparse(str(url or "")).netloc.lower()
        return host.endswith("hdhive.com")

    async def _fetch_hdhive_source(
        self,
        source: dict[str, Any],
        query: str | None,
        query_context: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        context = query_context or {}
        media_type = str(context.get("media_type") or "").strip().lower()
        tmdb_id = _positive_int(context.get("tmdb_id"))
        if media_type not in {"movie", "tv"} or not tmdb_id:
            add_log(
                "debug",
                "rss",
                "HDHive 需要订阅携带 TMDB ID，已跳过本次搜索",
                {"query": query, "media_type": media_type, "tmdb_id": context.get("tmdb_id")},
            )
            return []
        base_url = str(source.get("url") or HDHIVE_DEFAULT_URL).strip() or HDHIVE_DEFAULT_URL
        return await HdhiveBrowserClient(source, base_url).search_tmdb(media_type, tmdb_id, context)


class HdhiveBrowserClient:
    def __init__(self, source: dict[str, Any], base_url: str) -> None:
        self.source = source
        self.base_url = base_url.rstrip("/") + "/"
        self.name = str(source.get("name") or "HDHive").strip() or "HDHive"
        self.max_points = _hdhive_points_threshold(source)

    async def search_tmdb(self, media_type: str, tmdb_id: int, context: dict[str, Any]) -> list[SearchResult]:
        detail_url = urljoin(self.base_url, f"tmdb/{media_type}/{tmdb_id}")
        title = str(context.get("title") or "").strip()
        browser_result = await self._run_browser(detail_url, title, media_type, tmdb_id)
        return [
            SearchResult(
                title=item["title"],
                url=item["url"],
                source=f"site_plugin:{self.name}",
                message_id=item["message_id"],
                context=item["context"],
            )
            for item in browser_result
        ]

    async def _run_browser(self, detail_url: str, title: str, media_type: str, tmdb_id: int) -> list[dict[str, str]]:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            add_log("warning", "rss", "HDHive 浏览器依赖不可用", {"error": str(exc)})
            return []

        user_data_dir = _hdhive_user_data_dir(self.source)
        executable_path = _hdhive_executable_path(self.source)
        headless = _hdhive_headless(self.source)
        timeout_ms = _hdhive_timeout_ms(self.source)
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    executable_path=executable_path,
                    headless=headless,
                    locale="zh-CN",
                    viewport={"width": 1365, "height": 900},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                try:
                    page = browser.pages[0] if browser.pages else await browser.new_page()
                    return await self._read_page(page, detail_url, title, media_type, tmdb_id, timeout_ms)
                finally:
                    await browser.close()
        except Exception as exc:
            add_log(
                "warning",
                "rss",
                "HDHive 浏览器搜索失败",
                {"url": detail_url, "error": str(exc), "error_type": type(exc).__name__},
            )
            return []

    async def _read_page(self, page: Any, detail_url: str, title: str, media_type: str, tmdb_id: int, timeout_ms: int) -> list[dict[str, str]]:
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=timeout_ms)
        await _settle_page(page, timeout_ms)
        detail_page_url = page.url
        cards = extract_hdhive_resource_candidates(await _hdhive_detail_cards(page))
        ordered = order_hdhive_candidates(cards, self.max_points)
        if not ordered:
            add_log("debug", "rss", "HDHive 没有可用 115 资源", {"url": detail_page_url, "tmdb_id": tmdb_id, "cards": len(cards)})
            return []

        results: list[dict[str, str]] = []
        for candidate in ordered:
            link = await self._resource_link(page, candidate, timeout_ms)
            if not link:
                continue
            context = _hdhive_context(candidate, detail_page_url, media_type, tmdb_id, title)
            results.append({"title": candidate.title or title or "HDHive 115 resource", "url": link, "message_id": candidate.href, "context": context})
            if candidate.is_free_or_unlocked:
                break
        return _dedupe_hdhive_results(results)

    async def _resource_link(self, page: Any, candidate: HdhiveResourceCandidate, timeout_ms: int) -> str:
        await page.goto(candidate.href, wait_until="domcontentloaded", timeout=timeout_ms)
        await _settle_page(page, timeout_ms)
        direct = _first_115(await _hdhive_page_text_and_links(page))
        if direct:
            return direct
        if candidate.unavailable or candidate.points > self.max_points:
            return ""
        clicked = await _click_hdhive_unlock(page, timeout_ms)
        if not clicked:
            return ""
        await _settle_page(page, timeout_ms)
        return _first_115(await _hdhive_page_text_and_links(page))


def extract_hdhive_resource_candidates(items: list[dict[str, Any]]) -> list[HdhiveResourceCandidate]:
    candidates: list[HdhiveResourceCandidate] = []
    seen: set[str] = set()
    for item in items:
        href = str(item.get("href") or "").strip()
        if not HDHIVE_RESOURCE_RE.search(urlparse(href).path):
            continue
        if href in seen:
            continue
        seen.add(href)
        context = _clean_hdhive_text(item.get("text"))
        title = _hdhive_candidate_title(context)
        candidates.append(
            HdhiveResourceCandidate(
                title=title,
                href=href,
                context=context,
                points=_hdhive_points(context),
                unlocked=_hdhive_unlocked(context),
                unavailable=_hdhive_unavailable(context),
            )
        )
    return candidates


def order_hdhive_candidates(candidates: list[HdhiveResourceCandidate], max_points: int) -> list[HdhiveResourceCandidate]:
    usable = [item for item in candidates if not item.unavailable and (item.is_free_or_unlocked or item.points <= max_points)]
    return sorted(usable, key=lambda item: (0 if item.is_free_or_unlocked else 1, item.points, -_hdhive_size_score(item.context), item.title))


def _hdhive_points_threshold(source: dict[str, Any]) -> int:
    for key in ("points_threshold", "max_points", "unlock_points_threshold"):
        value = _positive_int(source.get(key))
        if value is not None:
            return value
    return 0


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


def _hdhive_headless(source: dict[str, Any]) -> bool:
    value = str(source.get("headless") if "headless" in source else os.getenv("TOGO115_HDHIVE_HEADLESS", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _hdhive_timeout_ms(source: dict[str, Any]) -> int:
    try:
        return max(8000, min(int(float(source.get("browser_timeout") or 20000)), 60000))
    except (TypeError, ValueError):
        return 20000


async def _settle_page(page: Any, timeout_ms: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
    except Exception:
        await asyncio.sleep(0.5)


async def _hdhive_detail_cards(page: Any) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href*="/resource/115/"]')).map((anchor) => {
          let node = anchor;
          let text = '';
          for (let i = 0; i < 6 && node; i += 1) {
            text = (node.innerText || node.textContent || '').trim();
            if (text && text.length > 20) break;
            node = node.parentElement;
          }
          return { href: anchor.href, text };
        })
        """
    )


async def _hdhive_page_text_and_links(page: Any) -> str:
    return await page.evaluate(
        """
        () => {
          const links = Array.from(document.querySelectorAll('a[href]')).map((anchor) => `${anchor.textContent || ''}\\n${anchor.href}`).join('\\n');
          return `${document.body ? document.body.innerText : ''}\\n${links}`;
        }
        """
    )


async def _click_hdhive_unlock(page: Any, timeout_ms: int) -> bool:
    buttons = page.locator("button")
    count = await buttons.count()
    for index in range(count):
        button = buttons.nth(index)
        try:
            text = (await button.inner_text(timeout=1000)).strip()
        except Exception:
            text = ""
        if not _is_unlock_button(text):
            continue
        if not await button.is_enabled():
            continue
        await button.click(timeout=timeout_ms)
        return True
    return False


def _is_unlock_button(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value and ("解锁" in value or "获取资源" in value or "查看链接" in value))


def _first_115(text: str) -> str:
    for link in extract_115_links(text):
        if is_115_share_link(link):
            return link
    return ""


def _hdhive_context(candidate: HdhiveResourceCandidate, detail_url: str, media_type: str, tmdb_id: int, title: str) -> str:
    parts = [
        title,
        candidate.context,
        f"HDHive: {detail_url}",
        f"TMDB {media_type}:{tmdb_id}",
        f"points={candidate.points}",
    ]
    return "\n".join(part for part in parts if part)


def _dedupe_hdhive_results(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _clean_hdhive_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _hdhive_candidate_title(text: str) -> str:
    if not text:
        return "HDHive 115 resource"
    parts = re.split(r"(?:发布于|已解锁|需要|疑似失效|失效|管理员)", text, 1)
    title = parts[0].strip(" -·")
    return title[:160] or text[:160]


def _hdhive_points(text: str) -> int:
    value = str(text or "")
    if "免费" in value or "已解锁" in value:
        return 0
    patterns = (
        r"(?:需要|消耗|花费|解锁)\s*(\d{1,5})\s*(?:积分|点)",
        r"(\d{1,5})\s*(?:积分|点)\s*(?:解锁|查看|获取)",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return int(match.group(1))
    if "积分" in value and "解锁" in value:
        return 999999
    return 0


def _hdhive_unlocked(text: str) -> bool:
    value = str(text or "")
    return "已解锁" in value or "资源链接" in value or bool(extract_115_links(value))


def _hdhive_unavailable(text: str) -> bool:
    value = str(text or "")
    return any(word in value for word in ("疑似失效", "已失效", "链接失效", "资源失效", "不可用"))


def _hdhive_size_score(text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB|TiB|GiB|MiB)", str(text or ""), re.I)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2).upper()
    if unit in {"TB", "TIB"}:
        return number * 1024 * 1024
    if unit in {"GB", "GIB"}:
        return number * 1024
    return number


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
