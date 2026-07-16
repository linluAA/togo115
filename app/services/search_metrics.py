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
    "attach_duplicates": 0,
    "attach_expired": 0,
    "attach_save_failed": 0,
    "attach_mismatch": 0,
    "attach_recheck": 0,
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


def record_telegram_search(payload: dict[str, Any]) -> None:
    event = {
        "ts": time.time(),
        "kind": "telegram_search",
        "title": str(payload.get("title") or "")[:120],
        "resolve_ms": int(payload.get("resolve_ms") or 0),
        "search_ms": int(payload.get("search_ms") or 0),
        "extract_ms": int(payload.get("extract_ms") or 0),
        "total_ms": int(payload.get("total_ms") or 0),
        "index_hits": int(payload.get("index_hits") or 0),
        "remote_hits": int(payload.get("remote_hits") or 0),
        "cancelled": int(payload.get("cancelled") or 0),
        "cancel_rate": float(payload.get("cancel_rate") or 0),
        "force_remote": bool(payload.get("force_remote") or False),
        "cache": payload.get("cache") or {},
    }
    with _LOCK:
        _EVENTS.appendleft(event)
        _COUNTERS["telegram_searches"] = int(_COUNTERS["telegram_searches"]) + 1
        _COUNTERS["index_hits"] = int(_COUNTERS["index_hits"]) + event["index_hits"]
        _COUNTERS["remote_hits"] = int(_COUNTERS["remote_hits"]) + event["remote_hits"]
        _COUNTERS["cancelled"] = int(_COUNTERS["cancelled"]) + event["cancelled"]
        _COUNTERS["resolve_ms_sum"] = int(_COUNTERS["resolve_ms_sum"]) + event["resolve_ms"]
        _COUNTERS["search_ms_sum"] = int(_COUNTERS["search_ms_sum"]) + event["search_ms"]
        _COUNTERS["extract_ms_sum"] = int(_COUNTERS["extract_ms_sum"]) + event["extract_ms"]
        _COUNTERS["total_ms_sum"] = int(_COUNTERS["total_ms_sum"]) + event["total_ms"]
        _SAMPLES["resolve_ms"].append(event["resolve_ms"])
        _SAMPLES["search_ms"].append(event["search_ms"])
        _SAMPLES["extract_ms"].append(event["extract_ms"])
        _SAMPLES["total_ms"].append(event["total_ms"])


def record_115_validation(payload: dict[str, Any]) -> None:
    event = {
        "ts": time.time(),
        "kind": "115_validation",
        "subscription_id": payload.get("id"),
        "115_ms": int(payload.get("115_ms") or 0),
        "checked_115": int(payload.get("checked_115") or 0),
        "expired_115": int(payload.get("expired_115") or 0),
        "recheck_115": int(payload.get("recheck_115") or 0),
        "created": int(payload.get("created") or 0),
        "from_index": bool(payload.get("from_index") or False),
    }
    with _LOCK:
        _EVENTS.appendleft(event)
        _COUNTERS["115_checks"] = int(_COUNTERS["115_checks"]) + event["checked_115"]
        _COUNTERS["115_ms_sum"] = int(_COUNTERS["115_ms_sum"]) + event["115_ms"]
        _COUNTERS["115_expired"] = int(_COUNTERS["115_expired"]) + event["expired_115"]
        _COUNTERS["115_recheck"] = int(_COUNTERS["115_recheck"]) + event["recheck_115"]
        _SAMPLES["115_ms"].append(event["115_ms"])


def record_attach_outcome(payload: dict[str, Any]) -> None:
    """Track why TG attach did or did not create a deliverable resource."""
    created = int(payload.get("created") or 0)
    duplicates = int(payload.get("duplicates") or 0)
    expired = int(payload.get("expired_115") or 0)
    save_failed = int(payload.get("save_failed") or 0)
    recheck = int(payload.get("recheck_115") or 0)
    raw_matched = int(payload.get("raw_matched") or 0)
    candidates = int(payload.get("candidates") or 0)
    mismatch = 1 if candidates > 0 and raw_matched == 0 and created == 0 else 0
    event = {
        "ts": time.time(),
        "kind": "attach_outcome",
        "subscription_id": payload.get("id"),
        "created": created,
        "duplicates": duplicates,
        "expired_115": expired,
        "save_failed": save_failed,
        "recheck_115": recheck,
        "raw_matched": raw_matched,
        "candidates": candidates,
        "mismatch": mismatch,
        "from_index": bool(payload.get("from_index") or False),
    }
    with _LOCK:
        _EVENTS.appendleft(event)
        _COUNTERS["attach_runs"] = int(_COUNTERS["attach_runs"]) + 1
        _COUNTERS["attach_created"] = int(_COUNTERS["attach_created"]) + created
        _COUNTERS["attach_duplicates"] = int(_COUNTERS["attach_duplicates"]) + duplicates
        _COUNTERS["attach_expired"] = int(_COUNTERS["attach_expired"]) + expired
        _COUNTERS["attach_save_failed"] = int(_COUNTERS["attach_save_failed"]) + save_failed
        _COUNTERS["attach_mismatch"] = int(_COUNTERS["attach_mismatch"]) + mismatch
        _COUNTERS["attach_recheck"] = int(_COUNTERS["attach_recheck"]) + recheck


def record_prewarm(payload: dict[str, Any]) -> None:
    with _LOCK:
        _COUNTERS["prewarm_runs"] = int(_COUNTERS["prewarm_runs"]) + 1
        _COUNTERS["prewarm_indexed"] = int(_COUNTERS["prewarm_indexed"]) + int(payload.get("indexed") or 0)
        _EVENTS.appendleft({"ts": time.time(), "kind": "prewarm", **{k: payload.get(k) for k in ("sources", "dialogs", "indexed", "elapsed_ms")}})


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
    return {
        "concurrency": runtime.SUBSCRIPTION_SEARCH_CONCURRENCY,
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
