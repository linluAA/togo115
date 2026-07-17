from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

from app.db import add_log
from app.services.link import (
    html_page_title,
    link_context_from_html,
    strip_html,
    title_from_link_context,
    extract_download_links,
)
from app.services.link.downloads import is_115_share_link, is_valid_download_link
from app.services.types import SearchResult


class RssTorznabSitePageMixin:
    def _parse_magnet_web_page(self, source: dict[str, Any], page_url: str, html_text: str, source_context: str = "") -> list[SearchResult]:
        name = str(source.get("name") or "\u8ba2\u9605\u6e90").strip()
        normalized_html = unescape(html_text or "")
        page_title = html_page_title(normalized_html, name)
        page_text = strip_html(normalized_html)
        links = self._site_plugin_links(normalized_html, page_text)
        self._log_bt1207_no_links(page_url, links, page_title, normalized_html, page_text)

        results, filtered = self._results_from_links(source, name, page_url, page_title, page_text, normalized_html, source_context, links)
        self._log_bt1207_filtered(page_url, source, links, results, filtered, page_title)
        return results

    def _site_plugin_links(self, normalized_html: str, page_text: str) -> list[str]:
        links = [*extract_download_links(normalized_html), *extract_download_links(page_text)]
        return self._dedupe_links([link for link in links if self._is_site_plugin_download_link(link)])

    def _is_site_plugin_download_link(self, link: str) -> bool:
        value = str(link or "").strip().casefold()
        if not is_valid_download_link(link) or is_115_share_link(link):
            return False
        return value.startswith("magnet:?") or value.endswith(".torrent") or ".torrent?" in value

    def _results_from_links(
        self,
        source: dict[str, Any],
        name: str,
        page_url: str,
        page_title: str,
        page_text: str,
        normalized_html: str,
        source_context: str,
        links: list[str],
    ) -> tuple[list[SearchResult], int]:
        results: list[SearchResult] = []
        filtered = 0
        for link in links:
            context = link_context_from_html(normalized_html, link) or page_text[:1200]
            size_context = _magnet_size_context(page_text, source_context, context)
            title_context = "\n".join(part for part in (source_context, context, size_context) if part)
            title = title_from_link_context(title_context, page_title)
            text = "\n".join(part for part in (title, page_title, source_context, context, size_context) if part)
            if not self._source_matches_filters(source, text):
                filtered += 1
                continue
            results.append(SearchResult(title=title, url=link, source=f"{self._source_type(source)}:{name}", message_id=page_url, context=text))
        return results, filtered

    def _log_bt1207_no_links(self, page_url: str, links: list[str], page_title: str, normalized_html: str, page_text: str) -> None:
        if self._is_bt1207_url(page_url) and "/detail/" in urlparse(page_url).path and not links:
            add_log(
                "debug",
                "rss",
                "BT1207 \u8be6\u60c5\u9875\u672a\u89e3\u6790\u5230\u78c1\u529b\u6216\u79cd\u5b50\u54c8\u5e0c",
                {"url": page_url, "title": page_title, "length": len(normalized_html), "snippet": page_text[:260]},
            )

    def _log_bt1207_filtered(self, page_url: str, source: dict[str, Any], links: list[str], results: list[SearchResult], filtered: int, page_title: str) -> None:
        if self._is_bt1207_url(page_url) and "/detail/" in urlparse(page_url).path and links and not results:
            add_log(
                "debug",
                "rss",
                "BT1207 \u8be6\u60c5\u9875\u78c1\u529b\u88ab\u8ba2\u9605\u6e90\u8fc7\u6ee4\u6761\u4ef6\u8df3\u8fc7",
                {"url": page_url, "title": page_title, "links": len(links), "filtered": filtered, "keywords": source.get("keywords"), "quality": source.get("quality")},
            )


def _magnet_size_context(page_text: str, *near_texts: str) -> str:
    for text in near_texts:
        size = _first_size_text(text)
        if size:
            return f"\u6587\u4ef6\u5927\u5c0f\uff1a{size}"
    size = _first_size_text(page_text)
    return f"\u6587\u4ef6\u5927\u5c0f\uff1a{size}" if size else ""


def _first_size_text(text: str) -> str:
    value = str(text or "")
    patterns = (
        r"(?:\u6587\u4ef6\u5927\u5c0f|\u5927\u5c0f|Size)\s*[:\uff1a]?\s*(\d+(?:\.\d+)?)\s*(TiB|GiB|MiB|TB|GB|MB|T|G|M)",
        r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(TiB|GiB|MiB|TB|GB|MB|T|G|M)(?![A-Za-z])",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            number = match.group(1)
            unit = match.group(2).upper()
            unit = {"GIB": "GB", "MIB": "MB", "TIB": "TB", "G": "GB", "M": "MB", "T": "TB"}.get(unit, unit)
            return f"{number} {unit}"
    return ""
