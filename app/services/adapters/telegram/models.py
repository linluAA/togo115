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


def index_origin_source(value: Any) -> str:
    """Extract dialog source from TelegramIndex / TelegramIndex:<id> labels."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text == "TelegramIndex":
        return ""
    if text.startswith("TelegramIndex:"):
        return text.split(":", 1)[1].strip()
    return ""


def is_telegram_index_source(value: Any) -> bool:
    text = str(value or "").strip()
    return text == "TelegramIndex" or text.startswith("TelegramIndex:")


@dataclass
class TelegramSearchSharedState:
    """Reusable state shared between Telegram fast and full search stages."""

    dialogs: list[dict[str, Any]] | None = None
    seen_message_ids: dict[str, set[int]] = field(default_factory=dict)
    seen_urls: set[str] = field(default_factory=set)
    force_remote: bool = False
    # When set, remote search only touches these dialogs (targeted recheck).
    preferred_sources: list[str] = field(default_factory=list)

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
            origin = index_origin_source(source) or (source if source and not is_telegram_index_source(source) else "")
            if message_id and origin:
                try:
                    self.seen_messages_for(origin).add(int(message_id))
                except (TypeError, ValueError):
                    pass
        return kept

    def set_preferred_sources_from_results(self, results: list[Any]) -> None:
        """Record dialog sources that produced index hits for targeted remote recheck."""
        preferred: list[str] = []
        seen: set[str] = set()
        for result in results or []:
            origin = index_origin_source(getattr(result, "source", ""))
            if not origin or origin in seen:
                continue
            seen.add(origin)
            preferred.append(origin)
        if preferred:
            self.preferred_sources = preferred

    def filter_dialogs(self, dialogs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Optionally narrow dialogs to preferred sources during force_remote recheck."""
        if not self.force_remote or not self.preferred_sources:
            return dialogs
        wanted = {str(item).strip() for item in self.preferred_sources if str(item).strip()}
        if not wanted:
            return dialogs
        narrowed = [
            dialog
            for dialog in dialogs
            if str(dialog.get("canonical") or dialog.get("source") or "").strip() in wanted
        ]
        return narrowed or dialogs
