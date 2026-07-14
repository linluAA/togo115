from __future__ import annotations

import asyncio
import sys
import time
from html import unescape
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse

import httpx
from telethon import TelegramClient

from app.db import add_log
from app.services.integration_state import module_proxy
from app.services.link_parser import (
    HTTP_URL_RE,
    TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE,
    TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS,
    TELEGRAM_EXTERNAL_PAGE_HOSTS,
    TELEGRAM_EXTERNAL_PAGE_MAX_FETCHES,
    TELEGRAM_EXTERNAL_PAGE_TIMEOUT_SECONDS,
    TELEGRAM_HISTORY_MAX_RESULTS,
    TELEGRAM_LINK_BUTTON_WORDS,
    TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS,
    _clean_download_link,
    _html_hrefs,
    _message_button_values,
    extract_115_links,
    telegram_message_text,
)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _compat_httpx():
    module = sys.modules.get("app.services.integrations")
    return getattr(module, "httpx", httpx) if module is not None else httpx


class TelegramButtonLinkMixin:
    async def _click_buttons_for_links(self, message: Any, client: TelegramClient | None = None, entity: Any = None) -> list[tuple[str, str]]:
        started = time.perf_counter()
        state = {"clicked": 0, "click_ms": 0, "refresh_ms": 0, "button_count": 0}
        links: list[tuple[str, str]] = []
        external_pages: list[tuple[str, str]] = []

        def collect(text: Any, label: str) -> None:
            self._collect_button_text_links(text, label, links, external_pages)

        await self._scan_message_buttons(message, client, entity, collect, links, state)
        page_started = time.perf_counter()
        await self._collect_external_page_links(external_pages, collect)
        deduped = self._dedupe_link_pairs(links)
        self._log_button_expansion(message, state, external_pages, deduped, started, page_started)
        return deduped

    async def _scan_message_buttons(self, message: Any, client, entity, collect, links: list[tuple[str, str]], state: dict[str, int]) -> None:
        for row_index, row in enumerate(getattr(message, "buttons", None) or []):
            for col_index, button in enumerate(row):
                state["button_count"] += 1
                if state["clicked"] >= TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE or len(links) >= TELEGRAM_HISTORY_MAX_RESULTS:
                    break
                await self._process_message_button(message, row_index, col_index, button, client, entity, collect, state)

    async def _process_message_button(self, message: Any, row_index: int, col_index: int, button: Any, client, entity, collect, state: dict[str, int]) -> None:
        label = getattr(button, "text", "") or ""
        values = self._button_values(button, label)
        for value in values:
            collect(value, label)
        if not self._button_should_click(values):
            return
        try:
            state["clicked"] += 1
            click_started = time.perf_counter()
            response = await asyncio.wait_for(message.click(row_index, col_index), timeout=TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS)
            state["click_ms"] += _elapsed_ms(click_started)
            self._collect_button_response_links(response, label, collect)
            refresh_started = time.perf_counter()
            await self._collect_refreshed_message_links(message, client, entity, label, collect)
            state["refresh_ms"] += _elapsed_ms(refresh_started)
        except asyncio.TimeoutError:
            add_log("debug", "telegram", "点击 Telegram 消息按钮超时", {"message_id": getattr(message, "id", None), "button": label, "timeout": TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS})
        except Exception as exc:
            add_log("debug", "telegram", "点击 Telegram 消息按钮未取得链接", {"message_id": getattr(message, "id", None), "button": label, "error": str(exc), "error_type": type(exc).__name__})

    def _button_values(self, button: Any, label: str) -> list[Any]:
        values = [label, getattr(button, "url", None)]
        raw_button = getattr(button, "button", None)
        if raw_button is not None:
            values.extend([getattr(raw_button, "url", None), getattr(raw_button, "data", None)])
        return values

    def _collect_button_text_links(self, text: Any, label: str, links: list[tuple[str, str]], external_pages: list[tuple[str, str]]) -> None:
        value = text.decode("utf-8", errors="ignore") if isinstance(text, bytes) else str(text or "")
        for link in extract_115_links(value):
            links.append((link, "\n".join(part for part in (label, value) if part)))
        for page_url in self._external_resource_page_urls(value):
            external_pages.append((page_url, label))

    def _collect_button_response_links(self, response: Any, label: str, collect: Callable[[Any, str], None]) -> None:
        collect(getattr(response, "url", None), label)
        collect(getattr(response, "raw_text", None) or getattr(response, "message", None) or (response if isinstance(response, str) else None), label)
        collect(telegram_message_text(response), label)

    def _log_button_expansion(self, message: Any, state: dict[str, int], external_pages: list[tuple[str, str]], links: list[tuple[str, str]], started: float, page_started: float) -> None:
        if not state["button_count"]:
            return
        add_log(
            "debug",
            "telegram",
            "Telegram 按钮链接展开完成",
            {
                "message_id": getattr(message, "id", None),
                "buttons": state["button_count"],
                "clicked": state["clicked"],
                "external_pages": len(external_pages),
                "links": len(links),
                "click_ms": state["click_ms"],
                "refresh_ms": state["refresh_ms"],
                "external_page_ms": _elapsed_ms(page_started) if external_pages else 0,
                "total_ms": _elapsed_ms(started),
            },
        )

    def _button_should_click(self, values: list[Any]) -> bool:
        text = " ".join(str(value or "") for value in values).casefold()
        if extract_115_links(text) or self._external_resource_page_urls(text):
            return False
        return any(word in text for word in TELEGRAM_LINK_BUTTON_WORDS)

    def _external_resource_page_urls(self, value: Any) -> list[str]:
        text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else str(value or "")
        urls: list[str] = []
        seen: set[str] = set()
        for raw_url in HTTP_URL_RE.findall(unescape(text)):
            url = _clean_download_link(raw_url)
            # 115 share links are direct resources, not third-party pages to scrape.
            if extract_115_links(url):
                continue
            parsed = urlparse(url)
            host = (parsed.netloc or "").casefold().removeprefix("www.")
            if parsed.scheme.startswith("http") and host in TELEGRAM_EXTERNAL_PAGE_HOSTS and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    async def _collect_external_page_links(self, pages: list[tuple[str, str]], collect: Callable[[Any, str], None]) -> None:
        if not pages:
            return
        proxy = module_proxy("telegram")
        fetched = 0
        seen: set[str] = set()
        async with _compat_httpx().AsyncClient(proxy=proxy or None, timeout=TELEGRAM_EXTERNAL_PAGE_TIMEOUT_SECONDS, follow_redirects=True) as page_client:
            for page_url, label in pages:
                if page_url in seen or fetched >= TELEGRAM_EXTERNAL_PAGE_MAX_FETCHES:
                    continue
                seen.add(page_url)
                fetched += 1
                await self._collect_one_external_page(page_client, page_url, label, collect)

    async def _collect_one_external_page(self, page_client, page_url: str, label: str, collect: Callable[[Any, str], None]) -> None:
        page_started = time.perf_counter()
        try:
            response = await page_client.get(page_url)
            response.raise_for_status()
        except Exception as exc:
            add_log("debug", "telegram", "Telegram 外部资源页读取失败", {"url": page_url, "error": str(exc), "error_type": type(exc).__name__, "elapsed_ms": _elapsed_ms(page_started)})
            return
        html_text = response.text or ""
        page_label = "\n".join(part for part in (label, page_url) if part)
        collect(html_text, page_label)
        collect(unquote(html_text), page_label)
        for href in _html_hrefs(html_text):
            absolute = urljoin(str(response.url), href)
            collect(absolute, page_label)
            collect(unquote(absolute), page_label)
        add_log("debug", "telegram", "Telegram 外部资源页已解析", {"url": page_url, "links": len(extract_115_links(html_text)), "elapsed_ms": _elapsed_ms(page_started)})

    async def _collect_refreshed_message_links(self, message: Any, client: TelegramClient | None, entity: Any, label: str, collect: Callable[[Any, str], None]) -> None:
        if not client or not getattr(message, "id", None):
            return
        await asyncio.sleep(0.2)
        for peer in self._message_peer_candidates(message, entity):
            try:
                refreshed = await asyncio.wait_for(client.get_messages(peer, ids=int(message.id)), timeout=TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS)
                collect(telegram_message_text(refreshed), label)
                for value in _message_button_values(refreshed):
                    collect(value, label)
                return
            except Exception:
                continue

    def _dedupe_link_pairs(self, links: list[tuple[str, str]]) -> list[tuple[str, str]]:
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for link, text in links:
            if link not in seen:
                seen.add(link)
                deduped.append((link, text))
        return deduped
