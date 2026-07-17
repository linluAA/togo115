from __future__ import annotations

"""Search/runtime metrics public surface."""

from app.services.search_metrics_record import (
    record_115_validation,
    record_attach_outcome,
    record_job_event,
    record_prewarm,
    record_telegram_search,
)
from app.services.search_metrics_snapshot import clear_metrics, metrics_snapshot
from app.services.search_metrics_store import _COUNTERS, _EVENTS, _LOCK, _SAMPLES, _percentile, _sample_stats

__all__ = [
    "record_telegram_search",
    "record_115_validation",
    "record_attach_outcome",
    "record_prewarm",
    "record_job_event",
    "metrics_snapshot",
    "clear_metrics",
    "_COUNTERS",
    "_EVENTS",
    "_LOCK",
    "_SAMPLES",
    "_percentile",
    "_sample_stats",
]
