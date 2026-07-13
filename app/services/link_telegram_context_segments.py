from __future__ import annotations

from urllib.parse import urlparse

from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link_downloads import PAN115_LOOSE_URL_RE


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
    next_link_indexes = [line_index for line_index, value in enumerate(lines[index + 1:], start=index + 1) if _line_has_link_hint(value)]
    return min(next_link_indexes[0], index + 4, len(lines)) if next_link_indexes else min(len(lines), index + 4)
