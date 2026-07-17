from __future__ import annotations

"""Telegram bot magnet search package."""

from app.services.magnet.cache import (
    _cached_magnet_search,
    _magnet_search_cache,
    _store_magnet_search_cache,
    pending_magnet_choices,
    pending_magnet_detail,
    pending_magnet_label,
    pending_magnet_pick,
    pending_magnet_target_path,
)
from app.services.magnet.constants import TG_BOT_MAGNET_LIMIT
from app.services.magnet.ranking import (
    _bot_title_or_alias_matches,
    _rank_magnet_results,
    _resource_size,
)
from app.services.magnet.reply import magnet_results_reply, magnet_results_reply_markup
from app.services.magnet.search import (
    _fast_magnet_queries,
    _fast_magnet_query_batches,
    _fast_source_options,
    _fetch_priority_sources,
    _fetch_priority_sources_until_ranked,
    search_magnets_for_tmdb,
    tmdb_search_choices,
)

__all__ = [
    "TG_BOT_MAGNET_LIMIT",
    "tmdb_search_choices",
    "search_magnets_for_tmdb",
    "magnet_results_reply",
    "magnet_results_reply_markup",
    "pending_magnet_pick",
    "pending_magnet_choices",
    "pending_magnet_target_path",
    "pending_magnet_detail",
    "pending_magnet_label",
    "_bot_title_or_alias_matches",
    "_cached_magnet_search",
    "_fast_magnet_queries",
    "_fast_magnet_query_batches",
    "_fast_source_options",
    "_magnet_search_cache",
    "_fetch_priority_sources",
    "_fetch_priority_sources_until_ranked",
    "_rank_magnet_results",
    "_resource_size",
    "_store_magnet_search_cache",
]
