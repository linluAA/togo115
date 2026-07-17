from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


_LOCK = threading.Lock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=200)
_SAMPLE_LIMIT = 120
_SAMPLES: dict[str, deque[int]] = {
    "resolve_ms": deque(maxlen=_SAMPLE_LIMIT),
    "search_ms": deque(maxlen=_SAMPLE_LIMIT),
    "extract_ms": deque(maxlen=_SAMPLE_LIMIT),
    "total_ms": deque(maxlen=_SAMPLE_LIMIT),
    "115_ms": deque(maxlen=_SAMPLE_LIMIT),
    "job_ms": deque(maxlen=_SAMPLE_LIMIT),
    "magnet_ms": deque(maxlen=_SAMPLE_LIMIT),
}
_COUNTERS: dict[str, float | int] = {
    "telegram_searches": 0,
    "index_hits": 0,
    "remote_hits": 0,
    "cancelled": 0,
    "resolve_ms_sum": 0,
    "search_ms_sum": 0,
    "extract_ms_sum": 0,
    "total_ms_sum": 0,
    "115_checks": 0,
    "115_ms_sum": 0,
    "115_expired": 0,
    "115_recheck": 0,
    "prewarm_runs": 0,
    "prewarm_indexed": 0,
    "attach_runs": 0,
    "attach_created": 0,
    "jobs_done": 0,
    "jobs_failed": 0,
    "jobs_requeued": 0,
    "jobs_duration_ms_sum": 0,
    "attach_duplicates": 0,
    "attach_expired": 0,
    "attach_save_failed": 0,
    "attach_mismatch": 0,
    "attach_recheck": 0,
    "magnet_searches": 0,
    "magnet_early_stops": 0,
    "magnet_cache_hits": 0,
    "magnet_ms_sum": 0,
    "index_queries": 0,
    "index_fts_hits": 0,
    "index_like_hits": 0,
    "index_recent_hits": 0,
}



def _percentile(samples: list[int], ratio: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(int(value) for value in samples)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[rank])

def _sample_stats(name: str) -> dict[str, float]:
    samples = list(_SAMPLES.get(name) or ())
    return {
        "p50": round(_percentile(samples, 0.50), 1),
        "p95": round(_percentile(samples, 0.95), 1),
        "count": len(samples),
    }
