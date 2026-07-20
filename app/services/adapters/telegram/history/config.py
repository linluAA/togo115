from __future__ import annotations

from typing import Any

from app.services.adapters.telegram.models import TelegramHistoryOptions
from app.services.link import (
    TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT,
    TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY,
    TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT,
    bounded_float,
    bounded_int,
    compact_search_text,
    years_from_text,
)


TELEGRAM_FAST_TOTAL_BUDGET_SECONDS = 18.0
TELEGRAM_FAST_QUERY_BUDGET_SECONDS = 2.0
TELEGRAM_FAST_RECENT_BUDGET_SECONDS = 4.0


def build_history_options(config: dict[str, Any]) -> TelegramHistoryOptions:
    history_limit = bounded_int(config.get("history_limit"), TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT, 1, TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT)
    fallback_limit = bounded_int(
        config.get("fallback_scan_limit"),
        history_limit,
        20,
        TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT,
    )
    messages_per_query = bounded_int(
        config.get("messages_per_query"),
        min(history_limit, TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY),
        1,
        history_limit,
    )
    return TelegramHistoryOptions(
        history_limit=history_limit,
        fallback_scan_limit=fallback_limit,
        messages_per_query=messages_per_query,
        total_budget=bounded_float(config.get("history_timeout"), TELEGRAM_FAST_TOTAL_BUDGET_SECONDS, 0.1, TELEGRAM_FAST_TOTAL_BUDGET_SECONDS),
        query_budget=bounded_float(config.get("history_query_timeout"), TELEGRAM_FAST_QUERY_BUDGET_SECONDS, 0.05, TELEGRAM_FAST_QUERY_BUDGET_SECONDS),
        recent_budget=bounded_float(config.get("history_fallback_timeout"), TELEGRAM_FAST_RECENT_BUDGET_SECONDS, 0.05, TELEGRAM_FAST_RECENT_BUDGET_SECONDS),
    )


def server_search_queries(queries: list[str], *, limit: int = 1) -> list[str]:
    """Pick the best remote Telegram search queries."""
    cleaned = [str(item or "").strip() for item in queries if str(item or "").strip()]
    if not cleaned:
        return []

    def sort_key(item: str) -> tuple[int, int, int, int, int]:
        compact = compact_search_text(item) or ""
        has_year = 1 if years_from_text(item) else 0
        # Prefer year queries first. Among year queries prefer latin transliterations
        # with more tokens (title + year) because they usually hit TG search better.
        token_count = max(1, len([part for part in item.split() if part]))
        has_cjk = 1 if any("\u3400" <= ch <= "\u9fff" for ch in item) else 0
        # Ascending: year first, then non-CJK, more tokens, then shorter compact form.
        return (-has_year, has_cjk, -token_count, len(compact), len(item))

    candidates = sorted(cleaned, key=sort_key)
    selected: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        key = compact_search_text(query) or ""
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(query)
        if len(selected) >= limit:
            break
    return selected


def adaptive_messages_per_query(base: int) -> int:
    """Shrink remote message fetch when recent extract latency is high."""
    try:
        from app.services.metrics.snapshot import metrics_snapshot

        p95 = float(((metrics_snapshot().get("telegram") or {}).get("p95_extract_ms") or 0))
    except Exception:
        return int(base)
    value = max(1, int(base or 1))
    if p95 <= 0:
        return value
    if p95 >= 900:
        return max(3, min(value, 5))
    if p95 >= 450:
        return max(4, min(value, 8))
    return value

