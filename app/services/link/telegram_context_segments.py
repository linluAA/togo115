from __future__ import annotations

import re

from urllib.parse import urlparse

from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link.downloads import PAN115_LOOSE_URL_RE


def _share_code_from_link(link: str) -> str:
    try:
        return urlparse(link).path.rstrip("/").split("/")[-1]
    except Exception:
        return ""


def _line_matches_link(line: str, link: str, share_code: str) -> bool:
    return link in line or bool(share_code and share_code in line)


def _line_has_link_hint(line: str) -> bool:
    lowered = line.casefold()
    return bool(PAN115_URL_RE.search(line) or PAN115_LOOSE_URL_RE.search(line) or "115.com/s" in lowered or "115cdn.com/s" in lowered)


def _previous_link_indexes(lines: list[str], index: int, share_code: str) -> list[int]:
    indexes = [line_index for line_index, value in enumerate(lines[:index]) if _line_has_link_hint(value)]
    if (
        indexes
        and indexes[-1] == index - 1
        and share_code
        and share_code in lines[index]
        and share_code not in lines[index - 1]
    ):
        indexes.pop()
    return indexes


def _next_link_end(lines: list[str], index: int) -> int:
    # Include only the share line and a short tail of non-title metadata
    # (password / size / notes). Stop before the next share or next resource title.
    end = min(len(lines), index + 1)
    for line_index in range(index + 1, min(len(lines), index + 4)):
        value = lines[line_index]
        if _line_has_link_hint(value):
            break
        if _looks_like_resource_title_line(value):
            break
        end = line_index + 1
    return end


def _looks_like_resource_title_line(line: str) -> bool:
    value = str(line or "").strip()
    if not value:
        return False
    if _line_has_link_hint(value):
        return False
    return bool(
        re.search(
            r"(?:^|[\s\[【(（])(?:电视剧|电影|动漫|动画|综艺|剧集|名称|片名|标题|资源)\s*[:：|｜]",
            value,
            re.I,
        )
        or re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d).{0,40}(?:1080|2160|4K|REMUX|BluRay|WEB|S\d{1,2}E\d{1,3})", value, re.I)
    )
