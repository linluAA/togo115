from __future__ import annotations

"""Shared resource matching surface for subscription and magnet flows.

Domain matching rules live under subscription.match.*; this module is the
stable import path for cross-package consumers (magnet, manual search, etc.).
"""

from typing import Any

from app.services.match_text import compact_match_text, years_from_text
from app.services.types import SearchResult


def result_text(result: SearchResult, *extra_texts: str) -> str:
    parts = [
        str(getattr(result, "context", "") or ""),
        str(getattr(result, "title", "") or ""),
        *(str(part or "") for part in extra_texts),
    ]
    return "\n".join(part for part in parts if part)


def result_debug_payload(result: SearchResult) -> dict[str, Any]:
    return {
        "title": str(getattr(result, "title", "") or "")[:120],
        "source": str(getattr(result, "source", "") or "")[:120],
        "message_id": getattr(result, "message_id", None),
        "url": str(getattr(result, "url", "") or "")[:200],
    }


def result_matches_subscription(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    """Delegate to subscription domain matcher (single source of truth)."""
    from app.services.subscription.match.core import (
        result_matches_subscription as _result_matches_subscription,
    )

    return _result_matches_subscription(subscription, result, *extra_texts)


__all__ = [
    "compact_match_text",
    "years_from_text",
    "result_text",
    "result_debug_payload",
    "result_matches_subscription",
]
