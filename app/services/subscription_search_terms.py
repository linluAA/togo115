from __future__ import annotations

from app.services.subscription_text_utils import (
    _compact_match_text,
    _safe_text,
    _title_without_year,
    _years_from_text,
)
from app.services.types import SearchResult


def _match_term(term: str | None) -> tuple[str, str] | None:
    raw = str(term or "").strip()
    compact = _compact_match_text(raw)
    if not raw or not compact:
        return None
    return raw.casefold(), compact


def _term_in_text(term: tuple[str, str], raw_haystack: str, compact_haystack: str) -> bool:
    raw_term, compact_term = term
    return raw_term in raw_haystack or compact_term in compact_haystack


def _subscription_release_year(subscription: dict) -> int | None:
    value = subscription.get("release_year")
    try:
        year = int(value) if value is not None and str(value).strip() else 0
    except (TypeError, ValueError):
        year = 0
    if 1900 <= year <= 2100:
        return year
    years = _years_from_text(subscription.get("title"))
    return min(years) if years else None


def _subscription_search_title(subscription: dict) -> str:
    title = _title_without_year(subscription.get("title")) or str(subscription.get("title") or "").strip()
    year = _subscription_release_year(subscription)
    if year and str(year) not in title:
        return f"{title} {year}"
    return title


def _extra_search_keywords(subscription: dict) -> list[str]:
    title = str(subscription.get("title") or "").strip()
    clean_title = _title_without_year(title)
    search_title = _subscription_search_title(subscription)
    title_terms = {_compact_match_text(title), _compact_match_text(clean_title), _compact_match_text(search_title)}
    extras: list[str] = []
    for keyword in subscription.get("keywords") or []:
        value = str(keyword or "").strip()
        clean_value = _title_without_year(value)
        compact = _compact_match_text(clean_value or value)
        if not value or not compact or compact in title_terms:
            continue
        extras.append(clean_value or value)
    return extras


def _subscription_required_terms(subscription: dict) -> tuple[tuple[str, str] | None, list[tuple[str, str]]]:
    title_term = _match_term(_title_without_year(subscription.get("title")) or subscription.get("title"))
    seen = {title_term[1]} if title_term else set()
    keyword_terms: list[tuple[str, str]] = []
    for keyword in subscription.get("keywords") or []:
        term = _match_term(_title_without_year(keyword) or keyword)
        if not term or len(term[1]) < 2 or term[1] in seen:
            continue
        seen.add(term[1])
        keyword_terms.append(term)
    return title_term, keyword_terms


def _subscription_match_text(result: SearchResult, *extra_texts: str) -> str:
    primary_text = "\n".join(
        part
        for part in [_safe_text(getattr(result, "context", "")), _safe_text(getattr(result, "title", ""))]
        if part
    )
    fallback_text = "\n".join(_safe_text(part) for part in extra_texts if part)
    return primary_text or fallback_text
