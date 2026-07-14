from __future__ import annotations

import re
from html import unescape

from app.services.link_downloads import BTIH_HASH_RE
from app.services.link_search_utils import years_from_text

HTML_ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<label>.*?)</a>", re.I | re.S)
HTML_HREF_RE = re.compile(r"\bhref\s*=\s*([\"'])(?P<href>.*?)\1|\bhref\s*=\s*(?P<bare>[^\s>]+)", re.I | re.S)
HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
HTML_CONTEXT_TAGS = ("li", "tr", "article", "section", "div", "p")

def _strip_html(html_text: str | None) -> str:
    if not html_text:
        return ""
    text = unescape(html_text)
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"</?(?:br|p|div|li|tr|td|th|h[1-6]|section|article|a)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _html_page_title(html_text: str | None, fallback: str) -> str:
    match = HTML_TITLE_RE.search(html_text or "")
    if not match:
        return fallback
    title = _strip_html(match.group(1))
    title = re.sub(r"\s*[-_｜|]\s*(樱花动漫|BT.*|迅雷下载|下载|磁力链接与种子详情).*$", "", title, flags=re.I).strip()
    return title or fallback


def _link_context_from_html(html_text: str, link: str) -> str:
    position = html_text.find(link)
    if position < 0:
        return ""
    for container in _html_container_fragments(html_text, position):
        context = _strip_html(container)
        if _title_from_link_context(context, ""):
            return context
    start = max(0, position - 900)
    end = min(len(html_text), position + len(link) + 900)
    return _strip_html(html_text[start:end])


def _title_from_link_context(context: str, fallback: str) -> str:
    noisy = {
        "复制链接",
        "复制",
        "下载",
        "磁力链接",
        "迅雷下载",
        "立即下载",
        "下载地址",
        "下载链接",
        "磁力下载",
        "资源列表",
        "资源下载",
        "精品推荐",
        "相关推荐",
        "相关资源",
        "在线",
        "资源详情",
    }
    noisy_fragments = ("文件数目", "文件数量", "文件大小", "收录时间", "创建时间", "更新时间", "分享时间")
    candidates = [line.strip(" -_·|") for line in context.splitlines() if line.strip()]
    scored: list[tuple[int, str]] = []
    for line in candidates:
        line = re.sub(r"\s*[-_｜|]\s*(BT.*|磁力链接与种子详情|迅雷下载|下载).*$", "", line, flags=re.I).strip(" -_·|")
        if line in noisy:
            continue
        if any(fragment in line for fragment in noisy_fragments):
            continue
        if "种子哈希" in line or BTIH_HASH_RE.search(line):
            continue
        if "magnet:?" in line or line.lower().endswith(".torrent"):
            continue
        if len(line) < 2:
            continue
        lowered = line.casefold()
        score = 1
        if re.search(r"(?i)(2160p|1080p|720p|web-?dl|hdtv|bluray|bdrip|x26[45]|hevc|avc|aac|flac|ddp)", line):
            score += 8
        if re.search(r"(?i)(s\d{1,2}e\d{1,3}|ep?\d{1,3}|第\s*\d{1,3}\s*[集话話])", line):
            score += 5
        if years_from_text(line):
            score += 3
        if len(line) >= 8:
            score += 2
        if any(word in lowered for word in ("详情", "简介", "地区", "导演", "主演", "类型")):
            score -= 4
        scored.append((score, line[:120]))
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]
    return fallback[:120]

def _html_hrefs(html_text: str) -> list[str]:
    hrefs: list[str] = []
    for anchor in HTML_ANCHOR_RE.finditer(html_text or ""):
        attrs = anchor.group("attrs") or ""
        href_match = HTML_HREF_RE.search(attrs)
        if href_match:
            hrefs.append(unescape((href_match.group("href") or href_match.group("bare") or "").strip()))
    return hrefs


def _html_container_fragments(html_text: str, position: int, max_len: int = 3200) -> list[str]:
    if not html_text or position < 0:
        return []
    fragments: list[str] = []
    seen: set[str] = set()
    for tag in HTML_CONTEXT_TAGS:
        start_re = re.compile(rf"<{tag}\b[^>]*>", re.I | re.S)
        close_re = re.compile(rf"</{tag}\s*>", re.I)
        starts = [match for match in start_re.finditer(html_text, 0, position + 1)]
        for start_match in reversed(starts[-8:]):
            for close_match in close_re.finditer(html_text, position, min(len(html_text), position + max_len)):
                fragment = html_text[start_match.start():close_match.end()]
                if 0 < len(fragment) <= max_len and fragment not in seen:
                    seen.add(fragment)
                    fragments.append(fragment)
                    break
    fragments.sort(key=len)
    return fragments


def _html_container_fragment(html_text: str, position: int, max_len: int = 3200) -> str:
    fragments = _html_container_fragments(html_text, position, max_len)
    return fragments[0] if fragments else ""



