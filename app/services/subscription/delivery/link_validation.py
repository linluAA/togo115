from __future__ import annotations

from app.services.sources.rss_torznab import SearchResult


async def filter_available_115_results(results: list[SearchResult]) -> list[SearchResult]:
    """Return results as-is (115 link validity detection removed)."""
    return results