from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from app.services.link_parser import (
    HTML_ANCHOR_RE,
    HTML_HREF_RE,
    MAGNET_WEB_DETAIL_LIMIT,
    _html_container_fragment,
    _strip_html,
    years_from_text,
)


class RssTorznabDetailCandidateMixin:
    def _magnet_web_detail_urls(self, source_url: str, html_text: str, release_year: int | None = None) -> list[str]:
        return [url for url, _ in self._magnet_web_detail_candidates(source_url, html_text, release_year)]

    def _magnet_web_detail_candidates(self, source_url: str, html_text: str, release_year: int | None = None) -> list[tuple[str, str]]:
        parsed_base = urlparse(source_url)
        ignored_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".xml", ".rss")
        by_url: dict[str, dict[str, Any]] = {}

        for href, label, nearby, years in self._magnet_web_link_candidates(html_text):
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "magnet:")):
                continue
            absolute = urljoin(source_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or parsed.netloc != parsed_base.netloc:
                continue
            path = parsed.path.lower()
            if path.endswith(ignored_extensions) or absolute.rstrip("/") == source_url.rstrip("/"):
                continue

            score = self._score_magnet_web_detail_path(path)
            if release_year and years and release_year in years:
                score += 4
            if score <= 0:
                continue

            normalized = urlunparse(parsed._replace(fragment=""))
            text = "\n".join(part for part in (label, nearby) if part)
            existing = by_url.setdefault(normalized, {"score": 0, "years": set(), "texts": []})
            existing["score"] = max(int(existing["score"]), score)
            existing["years"].update(years)
            if text and text not in existing["texts"]:
                existing["texts"].append(text)

        scored = self._scored_detail_candidates(by_url)
        if release_year:
            year_tagged = [item for item in scored if item[2]]
            same_year = [item for item in scored if item[2] and release_year in item[2]]
            if same_year:
                scored = same_year
            elif year_tagged and not self._is_bt1207_url(source_url):
                return []
        scored.sort(key=lambda item: item[0], reverse=True)
        return [(url, hint) for _, url, _, hint in scored[:MAGNET_WEB_DETAIL_LIMIT]]

    def _magnet_web_link_candidates(self, html_text: str) -> list[tuple[str, str, str, set[int]]]:
        candidates: list[tuple[str, str, str, set[int]]] = []
        for anchor in HTML_ANCHOR_RE.finditer(html_text or ""):
            attrs = anchor.group("attrs") or ""
            href_match = HTML_HREF_RE.search(attrs)
            if not href_match:
                continue
            href = unescape((href_match.group("href") or href_match.group("bare") or "").strip())
            label = _strip_html(anchor.group("label") or "")
            nearby = self._nearby_text_for_anchor(html_text or "", anchor.start(), anchor.end())
            candidates.append((href, label, nearby, years_from_text("\n".join([label, nearby]))))
        return candidates

    def _score_magnet_web_detail_path(self, path: str) -> int:
        score = 0
        if re.search(r"/(movie|detail|subject|vod|anime|resource|bt|show|thread|view|torrent)/", path):
            score += 3
        if re.search(r"/\d+\.html?$", path):
            score += 2
        elif path.endswith((".html", ".htm")):
            score += 1
        return score

    def _nearby_text_for_anchor(self, html_text: str, anchor_start: int, anchor_end: int) -> str:
        container = _html_container_fragment(html_text, anchor_start)
        if container:
            return _strip_html(container)
        start = max(0, anchor_start - 320)
        end = min(len(html_text), anchor_end + 320)
        return _strip_html(html_text[start:end])

    def _scored_detail_candidates(self, by_url: dict[str, dict[str, Any]]) -> list[tuple[int, str, set[int], str]]:
        return [
            (
                int(item["score"]),
                url,
                set(item["years"]),
                "\n".join(str(text) for text in item["texts"] if text)[:1200],
            )
            for url, item in by_url.items()
        ]
