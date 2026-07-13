from __future__ import annotations

from app.services.subscription_identity import (
    _release_year_matches,
    _result_title_identity_conflicts,
    _subscription_match_text,
    _subscription_required_terms,
    _term_in_text,
    _title_term_in_text,
    _tmdb_ids_from_text,
)
from app.services.subscription_quality import result_matches_quality_rules
from app.services.subscription_text_utils import _compact_match_text
from app.services.types import SearchResult


def result_matches_subscription(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    text = _subscription_match_text(result, *extra_texts)
    if not text:
        return False
    raw_haystack = text.casefold()
    compact_haystack = _compact_match_text(text)
    title_term, keyword_terms = _subscription_required_terms(subscription)
    if _result_title_identity_conflicts(subscription, result):
        return False
    if not _release_year_matches(subscription, result, text, *extra_texts):
        return False
    if not _tmdb_or_title_matches(subscription, text, title_term):
        return False
    return all(_term_in_text(term, raw_haystack, compact_haystack) for term in keyword_terms) and result_matches_quality_rules(subscription, result, *extra_texts)


def _tmdb_or_title_matches(subscription: dict, text: str, title_term: tuple[str, str] | None) -> bool:
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "").lstrip("0")
    text_tmdb_ids = _tmdb_ids_from_text(text)
    if subscription_tmdb_id and text_tmdb_ids:
        return subscription_tmdb_id in text_tmdb_ids
    return bool(title_term and _title_term_in_text(title_term, text))
