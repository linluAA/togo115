from __future__ import annotations

import re

from app.services.link_search_utils import years_from_text
from app.services.link_telegram_context_segments import (
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

def context_for_115_link(text: str | None, link: str, total_links: int) -> str:
    message = text or ""
    if not message or total_links <= 1:
        return message
    share_code = _share_code_from_link(link)
    lines = message.splitlines()
    for index, line in enumerate(lines):
        if _line_matches_link(line, link, share_code):
            start = _context_start_line(lines, index, share_code)
            context_lines = lines[start:_next_link_end(lines, index)]
            return "\n".join(part for part in context_lines if part.strip())
    position = message.find(link)
    if position < 0:
        return message[:500]
    start = max(0, position - 160)
    end = min(len(message), position + len(link) + 160)
    return message[start:end]


def _context_start_line(lines: list[str], index: int, share_code: str) -> int:
    previous_indexes = _previous_link_indexes(lines, index, share_code)
    segment_start = (previous_indexes[-1] + 1) if previous_indexes else 0
    fallback_start = max(segment_start, index - 8)
    title_markers = [
        (line_index, _resource_title_line_score(lines[line_index]))
        for line_index in range(segment_start, index + 1)
        if _resource_title_line_score(lines[line_index]) > 0
    ]
    strong_title_markers = [(line_index, score) for line_index, score in title_markers if score >= 2]
    if strong_title_markers:
        return max(strong_title_markers, key=lambda item: (item[1], item[0]))[0]
    if title_markers:
        return title_markers[-1][0]
    return fallback_start





