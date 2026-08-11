from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── Size limits for TelegramSearchSharedState collections ──────────────
_MAX_SEEN_URLS = 5000
_MAX_SEEN_MESSAGE_IDS = 200       # per-source buckets
_MAX_SEEN_MESSAGE_ID_BUCKET = 2000  # entries per bucket
_MAX_QUERY_DIALOG_CACHE = 500
_MAX_DIALOG_HIT_SCORES = 200
_EVICT_FRACTION = 0.2             # evict oldest 20% when limit is exceeded


def _evict_oldest(data: dict, max_size: int, fraction: float = _EVICT_FRACTION) -> None:
    """Remove the oldest *fraction* of entries when *data* exceeds *max_size*."""
    if len(data) <= max_size:
        return
    # If the dict tracks insertion order (Python 3.7+), the first items are oldest.
    # We simply pop the first N items.
    to_remove = int(max(1, len(data) * fraction))
    keys = list(data.keys())[:to_remove]
    for key in keys:
        data.pop(key, None)


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
    # Process/session hit scores for dialog ranking within one search-all flow.
    dialog_hit_scores: dict[str, int] = field(default_factory=dict)
    # Cache remote query results keyed by "source\0query" for fast→full reuse.
    query_dialog_cache: dict[str, list[Any]] = field(default_factory=dict)

    def seen_messages_for(self, source: str) -> set[int]:
        key = str(source or "")
        bucket = self.seen_message_ids.get(key)
        if bucket is None:
            bucket = set()
            self.seen_message_ids[key] = bucket
            _evict_oldest(self.seen_message_ids, _MAX_SEEN_MESSAGE_IDS)
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
            # Enforce seen_urls capacity before adding.
            if len(self.seen_urls) >= _MAX_SEEN_URLS:
                self.seen_urls.clear()
            self.seen_urls.add(url)
            kept.append(result)
            message_id = getattr(result, "message_id", None)
            source = str(getattr(result, "source", "") or "")
            origin = index_origin_source(source) or (source if source and not is_telegram_index_source(source) else "")
            if message_id and origin:
                try:
                    bucket = self.seen_messages_for(origin)
                    if len(bucket) >= _MAX_SEEN_MESSAGE_ID_BUCKET:
                        bucket.clear()
                    bucket.add(int(message_id))
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

    def note_dialog_hits(self, source: str, count: int = 1) -> None:
        key = str(source or "").strip()
        if not key or count <= 0:
            return
        self.dialog_hit_scores[key] = int(self.dialog_hit_scores.get(key, 0) or 0) + int(count)
        _evict_oldest(self.dialog_hit_scores, _MAX_DIALOG_HIT_SCORES)

    def query_dialog_cache_key(self, source: str, query: str) -> str:
        return f"{str(source or '').strip()}\0{str(query or '').strip()}"

    def get_cached_query_dialog_results(self, source: str, query: str) -> list[Any] | None:
        key = self.query_dialog_cache_key(source, query)
        if key not in self.query_dialog_cache:
            return None
        return list(self.query_dialog_cache.get(key) or [])

    def set_cached_query_dialog_results(self, source: str, query: str, results: list[Any]) -> None:
        key = self.query_dialog_cache_key(source, query)
        self.query_dialog_cache[key] = list(results or [])
        _evict_oldest(self.query_dialog_cache, _MAX_QUERY_DIALOG_CACHE)

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
