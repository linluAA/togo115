from __future__ import annotations

import re

from app.services.link.search_utils import years_from_text
from app.services.link.telegram_context_segments import (
    _line_matches_link,
    _next_link_end,
    _previous_link_indexes,
    _share_code_from_link,
)


def _resource_title_line_score(line: str | None) -> int:
    value = str(line or "").strip()
    if not value:
        return 0
    label_match = re.search(r"(?:^|[\s📺🎬🎞️💎、。\[【])(电视剧|电影|动漫|动画|综艺|剧集|名称|片名|标题|资源)\s*[：:]*", value, re.I)
    if not label_match:
        return 0
    if re.search(r"(标签|简介|主演|评分|类型|分类|大小|质量|TMDB\s*ID)", value, re.I):
        return 1 if years_from_text(value) else 0
    score = 2
    if years_from_text(value):
        score += 3
    if re.search(r"(S\d{1,2}E\d{1,3}|第\s*\d{1,3}\s*[集话話]|1080|2160|4K|REMUX|BluRay|WEB)", value, re.I):
        score += 1
    return score

def context_for_115_link(text: str | None, link: str, total_links: int = 0) -> str:
    """Return the local text segment belonging to one 115 share.

    Always prefer the nearest title/link segment. total_links is kept for
    compatibility with callers that pass multi-link counts, but single-link
    windows are also scoped so a neighboring title cannot claim this share.
    """
    message = text or ""
    if not message:
        return message
    share_code = _share_code_from_link(link)
    lines = message.splitlines()
    for index, line in enumerate(lines):
        if _line_matches_link(line, link, share_code):
            start = _context_start_line(lines, index, share_code)
            context_lines = lines[start:_next_link_end(lines, index)]
            scoped = "\n".join(part for part in context_lines if part.strip())
            return scoped or message
    position = message.find(link)
    if position < 0 and share_code:
        position = message.find(share_code)
    if position < 0:
        return message[:500]
    start = max(0, position - 160)
    end = min(len(message), position + max(len(link), len(share_code)) + 160)
    return message[start:end]


def _context_start_line(lines: list[str], index: int, share_code: str) -> int:
    previous_indexes = _previous_link_indexes(lines, index, share_code)
    segment_start = (previous_indexes[-1] + 1) if previous_indexes else 0
    fallback_start = max(segment_start, index - 8)
    # Prefer the nearest titled line above the share. Stronger distant titles in the
    # same window often belong to a different card that has not yet been closed by a link.
    title_markers = [
        (line_index, _resource_title_line_score(lines[line_index]))
        for line_index in range(segment_start, index + 1)
        if _resource_title_line_score(lines[line_index]) > 0
    ]
    if title_markers:
        # Walk upward from the link and stop at the closest strong title.
        for line_index, score in reversed(title_markers):
            if score >= 2:
                return line_index
        return title_markers[-1][0]

    # Many TG cards put a plain title line ("将夜 2026 S01E01") above a link-only
    # share without a "电视剧：" label. Keep a short unlabeled title window.
    for line_index in range(index - 1, max(segment_start, index - 4) - 1, -1):
        if _looks_like_plain_title_line(lines[line_index]):
            return line_index
    return fallback_start


def _looks_like_plain_title_line(line: str | None) -> bool:
    value = str(line or "").strip()
    if not value or len(value) < 2 or len(value) > 120:
        return False
    # Ignore scraped HTML/markup lines so external page URLs above a share stay in context.
    if "<" in value or ">" in value or value.casefold().startswith("http"):
        return False
    if "115.com/s/" in value or "115cdn.com/s/" in value or value.casefold().startswith("magnet:?"):
        return False
    if re.search(r"(提取码|访问码|密码|链接|复制|下载|文件大小|文件数量)", value, re.I):
        return False
    has_year = bool(years_from_text(value))
    has_episode = bool(re.search(r"(S\d{1,2}E\d{1,3}|第\s*\d{1,3}\s*[集话話])", value, re.I))
    has_cjk = bool(re.search(r"[\u3400-\u9fff]", value))
    return has_cjk and (has_year or has_episode)





