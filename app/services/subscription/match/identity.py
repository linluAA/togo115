from __future__ import annotations

from app.services.subscription.match.search_terms import (
    _extra_search_keywords,
    _match_term,
    _subscription_match_text,
    _subscription_release_year,
    _subscription_required_terms,
    _subscription_search_title,
    _term_in_text,
)
from app.services.subscription.match.source_identity import (
    _result_is_fallback_source,
    _result_is_primary_115_resource,
    _result_is_site_plugin,
    _result_priority,
)
from app.services.subscription.match.title_identity import (
    CJK_RE,
    TITLE_PREFIX_LABELS,
    TITLE_SUFFIX_BOUNDARY_CHARS,
    _is_title_prefix_boundary,
    _is_title_suffix_boundary,
    _title_fragment_in_text,
    _title_term_in_text,
)
from app.services.subscription.match.tmdb_year_guard import (
    TMDB_ID_RE,
    _release_year_matches,
    _result_has_subscription_tmdb_id,
    _result_title_identity_conflicts,
    _tmdb_ids_from_text,
    _year_guard_texts,
)

__all__ = [
    "CJK_RE",
    "TITLE_PREFIX_LABELS",
    "TITLE_SUFFIX_BOUNDARY_CHARS",
    "TMDB_ID_RE",
    "_extra_search_keywords",
    "_is_title_prefix_boundary",
    "_is_title_suffix_boundary",
    "_match_term",
    "_release_year_matches",
    "_result_has_subscription_tmdb_id",
    "_result_is_fallback_source",
    "_result_is_primary_115_resource",
    "_result_is_site_plugin",
    "_result_priority",
    "_result_title_identity_conflicts",
    "_subscription_match_text",
    "_subscription_release_year",
    "_subscription_required_terms",
    "_subscription_search_title",
    "_term_in_text",
    "_title_fragment_in_text",
    "_title_term_in_text",
    "_tmdb_ids_from_text",
    "_year_guard_texts",
]
