from __future__ import annotations

"""Magnet cache public surface."""

from app.services.magnet.cache_pending import (
    pending_magnet_choices,
    pending_magnet_detail,
    pending_magnet_label,
    pending_magnet_pick,
    pending_magnet_target_path,
    _load_pending_magnet_results,
    _prune_pending_magnet_results,
    _save_pending_magnet_results,
    _store_pending_magnet_results,
)
from app.services.magnet.cache_search import (
    _cached_magnet_search,
    _deserialize_search_results,
    _load_magnet_search_cache,
    _magnet_cache_key,
    _prune_magnet_search_cache,
    _save_magnet_search_cache,
    _serialize_search_result,
    _store_magnet_search_cache,
)
from app.services.magnet.constants import _magnet_search_cache, _pending_magnet_picks

__all__ = [
    "pending_magnet_pick",
    "pending_magnet_choices",
    "pending_magnet_target_path",
    "pending_magnet_detail",
    "pending_magnet_label",
    "_store_pending_magnet_results",
    "_cached_magnet_search",
    "_store_magnet_search_cache",
    "_magnet_search_cache",
    "_pending_magnet_picks",
]
