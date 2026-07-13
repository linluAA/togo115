from __future__ import annotations

import re
from typing import Any

from app.services.adapters.telegram_models import _TelegramHistoryOptions
from app.services.link_parser import (
    TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT,
    TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY,
    TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT,
    TELEGRAM_HISTORY_QUERY_BUDGET_SECONDS,
    TELEGRAM_HISTORY_RECENT_BUDGET_SECONDS,
    TELEGRAM_HISTORY_TOTAL_BUDGET_SECONDS,
    _bounded_float,
    _bounded_int,
    _compact_search_text,
    _years_from_text,
)


TELEGRAM_FAST_TOTAL_BUDGET_SECONDS = 18.0
TELEGRAM_FAST_QUERY_BUDGET_SECONDS = 2.0
TELEGRAM_FAST_RECENT_BUDGET_SECONDS = 4.0


def build_history_options(config: dict[str, Any]) -> _TelegramHistoryOptions:
    history_limit = _bounded_int(config.get("history_limit"), TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT, 1, TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT)
    fallback_limit = _bounded_int(
        config.get("fallback_scan_limit"),
        history_limit,
        20,
        TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT,
    )
    messages_per_query = _bounded_int(
        config.get("messages_per_query"),
        min(history_limit, TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY),
        1,
        history_limit,
    )
    return _TelegramHistoryOptions(
        history_limit=history_limit,
        fallback_scan_limit=fallback_limit,
        messages_per_query=messages_per_query,
        total_budget=_bounded_float(config.get("history_timeout"), TELEGRAM_FAST_TOTAL_BUDGET_SECONDS, 0.1, TELEGRAM_FAST_TOTAL_BUDGET_SECONDS),
        query_budget=_bounded_float(config.get("history_query_timeout"), TELEGRAM_FAST_QUERY_BUDGET_SECONDS, 0.05, TELEGRAM_FAST_QUERY_BUDGET_SECONDS),
        recent_budget=_bounded_float(config.get("history_fallback_timeout"), TELEGRAM_FAST_RECENT_BUDGET_SECONDS, 0.05, TELEGRAM_FAST_RECENT_BUDGET_SECONDS),
    )


def server_search_queries(queries: list[str], *, limit: int = 1) -> list[str]:
    candidates = sorted(
        queries,
        key=lambda item: (
            0 if _years_from_text(item) else 1,
            0 if re.search(r"\s", item.strip()) else 1,
            -len(_compact_search_text(item)),
        ),
    )
    selected: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        key = _compact_search_text(query)
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(query)
        if len(selected) >= limit:
            break
    return selected
