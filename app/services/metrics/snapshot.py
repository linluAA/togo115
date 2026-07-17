from __future__ import annotations

from typing import Any

from app.services.metrics.store import _COUNTERS, _EVENTS, _LOCK, _SAMPLES, _sample_stats


def metrics_snapshot() -> dict[str, Any]:

    from app.services.adapters.telegram.rate_limit import telegram_request_gate
    from app.services.adapters.telegram.scan.extract_cache import extract_cache_stats
    import app.services.subscription.runtime as runtime

    with _LOCK:
        searches = max(1, int(_COUNTERS["telegram_searches"]))
        checked = max(1, int(_COUNTERS["115_checks"]))
        recent = list(_EVENTS)[:30]
        counters = dict(_COUNTERS)
        latency = {
            "resolve_ms": _sample_stats("resolve_ms"),
            "search_ms": _sample_stats("search_ms"),
            "extract_ms": _sample_stats("extract_ms"),
            "total_ms": _sample_stats("total_ms"),
            "115_ms": _sample_stats("115_ms"),
        }
    try:
        desired_concurrency = runtime.desired_search_concurrency()
    except Exception:
        desired_concurrency = runtime.SUBSCRIPTION_SEARCH_CONCURRENCY
    queue_stats = {}
    try:
        from app.services.jobs import job_queue_stats

        queue_stats = job_queue_stats()
    except Exception:
        queue_stats = {}
    return {
        "worker_id": (queue_stats or {}).get("worker_id"),
        "concurrency": runtime.SUBSCRIPTION_SEARCH_CONCURRENCY,
        "desired_concurrency": desired_concurrency,
        "semaphore_limit": int(getattr(runtime, "subscription_search_semaphore_limit", 0) or 0),
        "jobs": {
            "done": int(counters.get("jobs_done", 0) or 0),
            "failed": int(counters.get("jobs_failed", 0) or 0),
            "requeued": int(counters.get("jobs_requeued", 0) or 0),
            "queue": queue_stats,
            "worker_id": (queue_stats or {}).get("worker_id"),
            "running_workers": (queue_stats or {}).get("running_workers", 0),
            "latency": _sample_stats("job_ms") if "job_ms" in _SAMPLES or True else {},
        },
        "telegram": {
            "searches": int(counters["telegram_searches"]),
            "avg_resolve_ms": round(int(counters["resolve_ms_sum"]) / searches, 1),
            "avg_search_ms": round(int(counters["search_ms_sum"]) / searches, 1),
            "avg_extract_ms": round(int(counters["extract_ms_sum"]) / searches, 1),
            "avg_total_ms": round(int(counters["total_ms_sum"]) / searches, 1),
            "p50_total_ms": latency["total_ms"]["p50"],
            "p95_total_ms": latency["total_ms"]["p95"],
            "p50_search_ms": latency["search_ms"]["p50"],
            "p95_search_ms": latency["search_ms"]["p95"],
            "p50_extract_ms": latency["extract_ms"]["p50"],
            "p95_extract_ms": latency["extract_ms"]["p95"],
            "p50_resolve_ms": latency["resolve_ms"]["p50"],
            "p95_resolve_ms": latency["resolve_ms"]["p95"],
            "index_hits": int(counters["index_hits"]),
            "remote_hits": int(counters["remote_hits"]),
            "cancelled": int(counters["cancelled"]),
        },
        "share_115": {
            "checks": int(counters["115_checks"]),
            "avg_ms": round(int(counters["115_ms_sum"]) / checked, 1) if int(counters["115_checks"]) else 0,
            "p50_ms": latency["115_ms"]["p50"],
            "p95_ms": latency["115_ms"]["p95"],
            "expired": int(counters["115_expired"]),
            "recheck": int(counters["115_recheck"]),
        },
        "attach": {
            "runs": int(counters["attach_runs"]),
            "created": int(counters["attach_created"]),
            "duplicates": int(counters["attach_duplicates"]),
            "expired": int(counters["attach_expired"]),
            "save_failed": int(counters["attach_save_failed"]),
            "mismatch": int(counters["attach_mismatch"]),
            "recheck": int(counters["attach_recheck"]),
        },
        "latency": latency,
        "cache": extract_cache_stats(),
        "gate": telegram_request_gate.stats(),
        "prewarm": {
            "runs": int(counters["prewarm_runs"]),
            "indexed": int(counters["prewarm_indexed"]),
        },
        "recent": recent,
    }

def clear_metrics() -> None:
    with _LOCK:
        _EVENTS.clear()
        for key in list(_COUNTERS):
            _COUNTERS[key] = 0
        for samples in _SAMPLES.values():
            samples.clear()
