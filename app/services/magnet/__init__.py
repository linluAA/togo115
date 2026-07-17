from __future__ import annotations

"""Telegram bot magnet search package (public surface)."""

from app.services.magnet.cache import (
    pending_magnet_choices,
    pending_magnet_detail,
    pending_magnet_label,
    pending_magnet_pick,
    pending_magnet_target_path,
)
from app.services.magnet.constants import TG_BOT_MAGNET_LIMIT
from app.services.magnet.reply import magnet_results_reply, magnet_results_reply_markup
from app.services.magnet.search import search_magnets_for_tmdb, tmdb_search_choices

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
]


def __getattr__(name: str):
    """Lazy access for test helpers / advanced callers."""
    if name in {
        "_bot_title_or_alias_matches",
        "_rank_magnet_results",
        "_resource_size",
        "_detail_title",
        "_detail_year",
        "_display_source",
        "_result_attr",
        "_subscription_from_detail",
        "_is_magnet_result",
        "_result_score",
    }:
        from app.services.magnet import ranking as ranking_mod

        return getattr(ranking_mod, name)
    if name in {
        "_cached_magnet_search",
        "_magnet_search_cache",
        "_store_magnet_search_cache",
        "_store_pending_magnet_results",
    }:
        from app.services.magnet import cache as cache_mod

        return getattr(cache_mod, name)
    if name in {
        "_fast_magnet_queries",
        "_fast_magnet_query_batches",
        "_fast_source_options",
        "_fetch_priority_sources",
        "_fetch_priority_sources_until_ranked",
    }:
        from app.services.magnet import search as search_mod

        return getattr(search_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
