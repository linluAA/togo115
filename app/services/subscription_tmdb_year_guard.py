from __future__ import annotations

import re

from app.services.subscription_result_utils import _result_text
from app.services.subscription_search_terms import _subscription_release_year, _subscription_required_terms
from app.services.subscription_source_identity import _result_is_primary_115_resource
from app.services.subscription_text_utils import _years_from_text
from app.services.subscription_title_identity import _title_fragment_in_text
from app.services.types import SearchResult


TMDB_ID_RE = re.compile(r"(?i)(?:\{?\s*tmdb\s*(?:id)?\s*[-_:： ]\s*(?P<id>\d{2,})\s*\}?)")


def _tmdb_ids_from_text(text: str | None) -> set[str]:
    ids: set[str] = set()
    for match in TMDB_ID_RE.finditer(text or ""):
        value = match.group("id").lstrip("0") or "0"
        ids.add(value)
    return ids


def _year_guard_texts(result: SearchResult, *extra_texts: str) -> list[str]:
    parts = [getattr(result, "title", ""), getattr(result, "context", ""), *extra_texts]
    texts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = str(part or "").strip()
        if not value:
            continue
        candidates = [value, *(line.strip() for line in value.splitlines() if line.strip())]
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            texts.append(candidate)
    return texts


def _result_has_subscription_tmdb_id(subscription: dict, text: str, *extra_texts: str) -> bool:
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "").lstrip("0")
    if not subscription_tmdb_id:
        return False
    combined_text = "\n".join(part for part in [text, *extra_texts] if part)
    return subscription_tmdb_id in _tmdb_ids_from_text(combined_text)


def _release_year_matches(subscription: dict, result: SearchResult, text: str, *extra_texts: str) -> bool:
    release_year = _subscription_release_year(subscription)
    if not release_year:
        return True
    if _result_has_subscription_tmdb_id(subscription, text, *extra_texts):
        return True
    text_years = _years_from_text(text)
    if text_years and release_year not in text_years:
        return False
    title_term, _ = _subscription_required_terms(subscription)
    for candidate in _year_guard_texts(result, *extra_texts):
        years = _years_from_text(candidate)
        if not years or release_year in years:
            continue
        if _title_fragment_in_text(title_term, candidate):
            return False
    return True


def _result_title_identity_conflicts(subscription: dict, result: SearchResult) -> bool:
    full_text = _result_text(result)
    if _result_has_subscription_tmdb_id(subscription, full_text):
        return False
    title = str(getattr(result, "title", "") or "").strip()
    if not title or not _years_from_text(title):
        return False
    title_term, _ = _subscription_required_terms(subscription)
    if not _title_fragment_in_text(title_term, title):
        release_year = _subscription_release_year(subscription)
        full_years = _years_from_text(full_text)
        if _result_is_primary_115_resource(result) and _title_fragment_in_text(title_term, full_text) and (not release_year or not full_years or release_year in full_years):
            return False
        return True
    release_year = _subscription_release_year(subscription)
    title_years = _years_from_text(title)
    return bool(release_year and title_years and release_year not in title_years)
