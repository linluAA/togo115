from __future__ import annotations

from typing import Any

from app.services.sources.rss_torznab import SearchResult

TG_BOT_MAGNET_LIMIT = 5
TG_BOT_MAGNET_TIMEOUT_SECONDS = 15
TG_BOT_MAGNET_FAST_RESPONSE_SECONDS = 10.5
TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS = 9.0
TG_BOT_MAGNET_SOURCE_CONCURRENCY = 4
TG_BOT_MAGNET_SOURCE_QUERY_LIMIT = 2
TG_BOT_MAGNET_DETAIL_LIMIT = 2
TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS = 0.08
TG_BOT_MAGNET_PICK_TTL_SECONDS = 1800
TG_BOT_MAGNET_PICK_MAX_ITEMS = 50
TG_BOT_MAGNET_CACHE_TTL_SECONDS = 2400
TG_BOT_MAGNET_CACHE_MAX_ITEMS = 80

_pending_magnet_picks: dict[str, dict[str, Any]] = {}
_magnet_search_cache: dict[str, dict[str, Any]] = {}
_PENDING_MAGNET_FLOW = "tg_bot_magnet_picks"
_MAGNET_SEARCH_CACHE_FLOW = "tg_bot_magnet_search_cache"
