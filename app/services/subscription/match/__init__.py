"""Matching helpers (title/year/quality/episodes).

Prefer concrete modules::

    from app.services.subscription.match.core import result_matches_subscription

Lazy re-exports below avoid circular imports when submodules load each other.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['compact_match_text', 'extra_search_keywords', 'normalize_quality_rules', 'result_debug_payload', 'result_is_fallback_source', 'result_matches_subscription', 'result_priority', 'result_skip_reason', 'result_text', 'skip_reason_summary', 'subscription_release_year', 'subscription_search_title', 'title_without_year', 'years_from_text']

_RESOLVE = {'result_matches_subscription': 'app.services.subscription.match.core', 'compact_match_text': 'app.services.subscription.match.text_utils', 'normalize_quality_rules': 'app.services.subscription.match.text_utils', 'title_without_year': 'app.services.subscription.match.text_utils', 'years_from_text': 'app.services.subscription.match.text_utils', 'extra_search_keywords': 'app.services.subscription.match.search_terms', 'subscription_release_year': 'app.services.subscription.match.search_terms', 'subscription_search_title': 'app.services.subscription.match.search_terms', 'result_debug_payload': 'app.services.subscription.match.result_utils', 'result_text': 'app.services.subscription.match.result_utils', 'result_skip_reason': 'app.services.subscription.match.skip_reasons', 'skip_reason_summary': 'app.services.subscription.match.skip_reasons', 'result_is_fallback_source': 'app.services.subscription.match.source_identity', 'result_priority': 'app.services.subscription.match.source_identity'}


def __getattr__(name: str) -> Any:
    if name not in _RESOLVE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(_RESOLVE[name]), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
