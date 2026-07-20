from __future__ import annotations

import re
from typing import Any

from app.services.text_cjk import normalize_cjk_for_match, query_match_aliases, title_prefix_aliases

YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
LOCAL_SEARCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)

def _split_filter_words(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,，;；\n\r]+", str(value or "")) if part.strip()]


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


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "enabled")


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def _compact_search_text(value: str | None) -> str:
    return LOCAL_SEARCH_DROP_RE.sub("", normalize_cjk_for_match(str(value or "")).casefold())


def _query_without_year(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"[\(（\[\【]\s*(?:19|20)\d{2}\s*[\)）\]\】]", " ", text)
    text = YEAR_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _search_title_variants(title: str | None) -> list[str]:
    raw = re.sub(r"\s+", " ", str(title or "").strip())
    if not raw:
        return []
    variants: list[str] = []

    def add(value: str | None) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if normalized and normalized not in variants:
            variants.append(normalized)

    # Prefer bare franchise names first so prefix/CJK aliases are not crowded out by
    # year parentheses variants when callers use a small max_queries budget.
    bases: list[str] = []
    for alias in title_prefix_aliases(raw):
        base = _query_without_year(alias) or alias
        add(base)
        if base not in bases:
            bases.append(base)
    for alias in title_prefix_aliases(raw):
        years = sorted(years_from_text(alias))
        base = _query_without_year(alias) or alias
        add(alias)
        if base and years:
            for year in years:
                add(f"{base} {year}")
                add(f"{base} ({year})")
                add(f"{base}（{year}）")
    return variants


def _expanded_search_queries(title: str, keywords: list[str], max_queries: int = 16) -> list[str]:
    base_queries = _search_title_variants(title)
    if not base_queries:
        return []
    title_keys = {_compact_search_text(query) for query in base_queries}
    clean_keywords: list[str] = []
    seen_keywords: set[str] = set()
    for item in keywords:
        for keyword in _search_title_variants(str(item or "").strip()) or [str(item or "").strip()]:
            key = _compact_search_text(keyword)
            if not keyword or not key or key in title_keys or key in seen_keywords:
                continue
            seen_keywords.add(key)
            clean_keywords.append(keyword)

    queries: list[str] = []

    def add(value: str | None) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if normalized and normalized not in queries:
            queries.append(normalized)

    # Core names first (no year decorations), then year variants, then keyword combos.
    bare = [q for q in base_queries if not years_from_text(q)]
    with_year = [q for q in base_queries if years_from_text(q)]
    for query in bare + with_year:
        add(query)
    for keyword in clean_keywords:
        keyword_key = _compact_search_text(keyword)
        for base_query in bare + with_year:
            if keyword_key and keyword_key in _compact_search_text(base_query):
                continue
            add(f"{base_query} {keyword}")
            if len(queries) >= max_queries:
                return queries
    return queries[:max_queries]


def _local_text_matches_query(text: str | None, query: str | None) -> bool:
    compact_text = _compact_search_text(text)
    if not compact_text:
        return False
    for candidate in query_match_aliases(query) or [str(query or "").strip()]:
        parts = [part for part in re.split(r"\s+", candidate) if part]
        if parts and all(_compact_search_text(part) in compact_text for part in parts):
            return True
    return False


