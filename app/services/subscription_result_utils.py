from __future__ import annotations

from typing import Any

from app.services.subscription_text_utils import _safe_text
from app.services.types import SearchResult


def _result_text(result: SearchResult, *extra_texts: str) -> str:
    return "\n".join(
        part
        for part in [_safe_text(getattr(result, "context", "")), _safe_text(getattr(result, "title", "")), *(_safe_text(part) for part in extra_texts)]
        if part
    )


def _result_debug_payload(result: SearchResult) -> dict[str, Any]:
    return {
        "title": _safe_text(getattr(result, "title", ""))[:120],
        "source": _safe_text(getattr(result, "source", ""))[:120],
        "message_id": getattr(result, "message_id", None),
        "url": _safe_text(getattr(result, "url", ""))[:200],
    }


