from __future__ import annotations

import time
from typing import Any

# Short window to skip identical subscription searches that were just completed.
RECENT_SEARCH_TTL_SECONDS = 45.0
RECENT_SEARCH_MAX_ITEMS = 256

_recent: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _key(subscription_id: int, *, incremental_telegram: bool) -> str:
    return f"{int(subscription_id)}:{1 if incremental_telegram else 0}"


def get_recent_search_results(subscription_id: int, *, incremental_telegram: bool = False) -> list[dict[str, Any]] | None:
    item = _recent.get(_key(subscription_id, incremental_telegram=incremental_telegram))
    if not item:
        return None
    stamp, results = item
    if time.monotonic() - stamp > RECENT_SEARCH_TTL_SECONDS:
        _recent.pop(_key(subscription_id, incremental_telegram=incremental_telegram), None)
        return None
    return list(results)


def store_recent_search_results(
    subscription_id: int,
    results: list[dict[str, Any]] | None,
    *,
    incremental_telegram: bool = False,
) -> None:
    if results is None:
        return
    if len(_recent) >= RECENT_SEARCH_MAX_ITEMS:
        # drop oldest ~25%
        ordered = sorted(_recent.items(), key=lambda kv: kv[1][0])
        for key, _ in ordered[: max(1, RECENT_SEARCH_MAX_ITEMS // 4)]:
            _recent.pop(key, None)
    _recent[_key(subscription_id, incremental_telegram=incremental_telegram)] = (time.monotonic(), list(results))


def clear_recent_search_results(subscription_id: int | None = None) -> None:
    if subscription_id is None:
        _recent.clear()
        return
    for flag in (True, False):
        _recent.pop(_key(int(subscription_id), incremental_telegram=flag), None)
