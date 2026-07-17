from __future__ import annotations

"""Shared title/text normalization helpers used by magnet ranking and subscription match."""

import re
from typing import Any

from app.services.text_cjk import normalize_cjk_for_match

MATCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def compact_match_text(value: str | None) -> str:
    return MATCH_DROP_RE.sub("", normalize_cjk_for_match(str(value or "")).casefold())


def years_from_text(value: str | None) -> set[int]:
    years: set[int] = set()
    for token in YEAR_RE.findall(str(value or "")):
        try:
            years.add(int(token))
        except Exception:
            continue
    return years


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
