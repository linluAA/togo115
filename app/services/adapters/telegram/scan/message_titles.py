from __future__ import annotations

import re

TITLE_LABEL_RE = re.compile(
    r"(?:^|[\s\[\u3010\uff08(])(?:\u7535\u89c6\u5267|\u7535\u5f71|\u52a8\u6f2b|\u52a8\u753b|\u7efc\u827a|\u5267\u96c6|\u77ed\u5267|\u756a\u5267|\u540d\u79f0|\u7247\u540d|\u5267\u540d|\u6807\u9898|\u8d44\u6e90\u540d|\u8d44\u6e90)\s*[:\uff1a\uff5c|]\s*",
    re.I,
)
TITLE_SKIP_RE = re.compile(r"(?:\u6807\u7b7e|\u7b80\u4ecb|\u4e3b\u6f14|\u8bc4\u5206|\u7c7b\u578b|\u5206\u7c7b|\u5927\u5c0f|\u8d28\u91cf|\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u94fe\u63a5|TMDB\s*ID)", re.I)
TITLE_CLEAN_RE = re.compile(
    r"^(?:[\s\[\u3010\uff08(])*(?:\u7535\u89c6\u5267|\u7535\u5f71|\u52a8\u6f2b|\u52a8\u753b|\u7efc\u827a|\u5267\u96c6|\u77ed\u5267|\u756a\u5267|\u540d\u79f0|\u7247\u540d|\u5267\u540d|\u6807\u9898|\u8d44\u6e90\u540d|\u8d44\u6e90)\s*[:\uff1a\uff5c|]\s*",
    re.I,
)
NON_TITLE_RE = re.compile(r"(?:\u63d0\u53d6\u7801|\u8bbf\u95ee\u7801|\u5bc6\u7801|\u590d\u5236|\u4e0b\u8f7d|\u94fe\u63a5|\u6587\u4ef6\u5927\u5c0f|\u6587\u4ef6\u6570\u91cf|\u6536\u5f55\u65f6\u95f4|\u5206\u4eab\u65f6\u95f4)", re.I)
EPISODE_QUALITY_RE = re.compile(r"(?i)(S\d{1,2}E\d{1,3}|\u7b2c\s*\d{1,3}\s*[\u96c6\u8bdd\u8a71]|1080p|2160p|4K|BluRay|WEB)")
EPISODE_MARKER_RE = re.compile(r"(?i)(S\d{1,2}E\d{1,3}|第\s*\d{1,3}\s*[集话話]|更新至|全\s*\d{1,3}\s*[集话話])")
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

def _telegram_resource_title(context: str | None) -> str:
    lines = [line.strip() for line in str(context or "").splitlines() if line.strip()]
    labeled = [_strip_title_label(line) for line in lines if _title_label_score(line) > 0]
    base = ""
    for title in labeled:
        if _usable_title_line(title):
            base = title[:120]
            break
    if not base:
        scored = _scored_title_lines(lines)
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            base = scored[0][1]
    if not base:
        return "Telegram 资源"
    return _enrich_title_with_episode_marker(base, str(context or ""))


def _enrich_title_with_episode_marker(title: str, context: str) -> str:
    """Keep episode/range markers in stored titles for coverage and dedupe.

    HDHive-style cards often put the drama name on one line and S01E01-E21 on
    another. Without the range in title, similar_title / covered_episodes
    cannot distinguish a newer pack from an older bare-title resource.
    """
    value = str(title or "").strip()
    if not value:
        return value
    if EPISODE_MARKER_RE.search(value):
        return value[:120]
    marker = _episode_marker_from_context(context)
    if not marker:
        return value[:120]
    combined = f"{value} {marker}".strip()
    return combined[:120]


def _episode_marker_from_context(context: str) -> str:
    text = str(context or "")
    if not text:
        return ""
    for pattern in (
        r"(?i)S\d{1,2}E\d{1,3}\s*(?:-|~|–|—|至|到)\s*E?\d{1,3}",
        r"(?i)S\d{1,2}E\d{1,3}",
        r"第\s*\d{1,3}\s*[-~–—至到]\s*\d{1,3}\s*[集话話]",
        r"更新至\s*第?\s*\d{1,3}\s*[集话話]?",
        r"全\s*\d{1,3}\s*[集话話]",
    ):
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+", "", match.group(0))
    return ""


def _scored_title_lines(lines: list[str]) -> list[tuple[int, str]]:
    scored: list[tuple[int, str]] = []
    for line in lines:
        title = _strip_title_label(line)
        if not _usable_title_line(title):
            continue
        score = 1
        if YEAR_RE.search(title):
            score += 4
        if EPISODE_QUALITY_RE.search(title):
            score += 2
        if 4 <= len(title) <= 80:
            score += 1
        scored.append((score, title[:120]))
    return scored


def _title_label_score(line: str) -> int:
    value = str(line or "").strip()
    if not value or TITLE_SKIP_RE.search(value):
        return 0
    if not TITLE_LABEL_RE.search(value):
        return 0
    return 2 if YEAR_RE.search(value) else 1


def _strip_title_label(line: str) -> str:
    value = str(line or "").strip()
    value = TITLE_CLEAN_RE.sub("", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"(?:链接|地址|提取码|访问码|密码)\s*[:：].*$", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" -_·|")


def _usable_title_line(line: str) -> bool:
    value = str(line or "").strip()
    if len(value) < 2:
        return False
    if "115.com/s/" in value or "115cdn.com/s/" in value or value.casefold().startswith("magnet:?"):
        return False
    if NON_TITLE_RE.search(value):
        return False
    return bool(re.search(r"[\u3400-\u9fffA-Za-z0-9]", value))
