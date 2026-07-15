from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TelegramHistoryOptions:
    history_limit: int
    fallback_scan_limit: int
    messages_per_query: int
    total_budget: float
    query_budget: float
    recent_budget: float


class TelegramSearchBudget:
    def __init__(self, seconds: float) -> None:
        self.total = seconds
        self.deadline = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def exhausted(self, reserve: float = 0.05) -> bool:
        return self.remaining <= reserve

    def timeout(self, cap: float) -> float:
        return max(0.05, min(cap, self.remaining))


@dataclass
class TelegramSearchSharedState:
    """Reusable state shared between Telegram fast and full search stages."""

    dialogs: list[dict[str, Any]] | None = None
    seen_message_ids: dict[str, set[int]] = field(default_factory=dict)
    seen_urls: set[str] = field(default_factory=set)
    force_remote: bool = False

    def seen_messages_for(self, source: str) -> set[int]:
        key = str(source or "")
        bucket = self.seen_message_ids.get(key)
        if bucket is None:
            bucket = set()
            self.seen_message_ids[key] = bucket
        return bucket

    def remember_results(self, results: list[Any]) -> list[Any]:
        """Filter out URLs already seen, then record the remaining ones."""
        if not results:
            return []
        kept: list[Any] = []
        for result in results:
            url = str(getattr(result, "url", "") or "")
            if not url:
                kept.append(result)
                continue
            if url in self.seen_urls:
                continue
            self.seen_urls.add(url)
            kept.append(result)
            message_id = getattr(result, "message_id", None)
            source = str(getattr(result, "source", "") or "")
            if message_id and source and source != "TelegramIndex":
                try:
                    self.seen_messages_for(source).add(int(message_id))
                except (TypeError, ValueError):
                    pass
        return kept
