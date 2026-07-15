from __future__ import annotations

import re
from typing import Any

from app.services.text_cjk import normalize_cjk_for_match


MATCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

def compact_match_text(value: str | None) -> str:
    return MATCH_DROP_RE.sub("", normalize_cjk_for_match(str(value or "")).casefold())


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _split_rule_words(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,?\n\r]+", str(value or "")) if part.strip()]


def normalize_quality_rules(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    accept_mode = str(value.get("accept_mode") or "all").strip().lower()
    if accept_mode not in ("all", "pack", "single"):
        accept_mode = "all"
    return {
        "preferred_quality": _split_rule_words(value.get("preferred_quality")),
        "exclude_keywords": _split_rule_words(value.get("exclude_keywords")),
        "release_groups": _split_rule_words(value.get("release_groups")),
        "accept_mode": accept_mode,
    }


def title_without_year(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"[\(（\[\【]\s*(?:19|20)\d{2}\s*[\)）\]\】]", " ", text)
    text = YEAR_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def years_from_text(text: str | None) -> set[int]:
    years: set[int] = set()
    value = text or ""
    for match in YEAR_RE.finditer(value):
        before = value[max(0, match.start() - 2):match.start()]
        after = value[match.end():match.end() + 6]
        if re.search(r"[xX×]\s*$", before) or re.match(r"\s*[xX×]\s*\d{3,4}", after):
            continue
        if re.match(r"\s*(?:[-/.]\s*\d{1,2}(?!\d)|年\s*\d{1,2}(?!\d))", after):
            continue
        try:
            year = int(match.group(0))
        except ValueError:
            continue
        if 1900 <= year <= 2100:
            years.add(year)
    return years


