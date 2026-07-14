from __future__ import annotations

from app.services.subscription.resource.resources import resource_dedupe_key as _resource_dedupe_key
from app.services.types import SearchResult


def _result_is_site_plugin(result: SearchResult) -> bool:
    return str(getattr(result, "source", "") or "").casefold().startswith(("magnet_web:", "site_plugin:"))


def _result_is_fallback_source(result: SearchResult) -> bool:
    source = str(getattr(result, "source", "") or "").casefold()
    return source.startswith(("rss:", "torznab:", "magnet_web:", "site_plugin:"))


def _result_is_primary_115_resource(result: SearchResult) -> bool:
    key = _resource_dedupe_key(getattr(result, "url", None))
    return bool(key and key[0] == "115" and not _result_is_fallback_source(result))


def _result_priority(result: SearchResult) -> int:
    try:
        return int(getattr(result, "priority", 0) or 0)
    except (TypeError, ValueError):
        return 0
