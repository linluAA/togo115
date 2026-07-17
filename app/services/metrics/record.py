from __future__ import annotations

import time
from typing import Any

from app.services.metrics.store import _COUNTERS, _EVENTS, _LOCK, _SAMPLES


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

def record_job_event(payload: dict[str, Any]) -> None:
    status = str(payload.get("status") or "")
    duration = int(payload.get("duration_ms") or 0)
    count = int(payload.get("count") or 0)
    with _LOCK:
        if status == "done":
            _COUNTERS["jobs_done"] = int(_COUNTERS.get("jobs_done", 0)) + 1
            if duration > 0:
                _COUNTERS["jobs_duration_ms_sum"] = int(_COUNTERS.get("jobs_duration_ms_sum", 0)) + duration
                _SAMPLES["job_ms"].append(duration)
        elif status == "failed":
            _COUNTERS["jobs_failed"] = int(_COUNTERS.get("jobs_failed", 0)) + 1
            if duration > 0:
                _SAMPLES["job_ms"].append(duration)
        elif status == "requeued":
            _COUNTERS["jobs_requeued"] = int(_COUNTERS.get("jobs_requeued", 0)) + max(1, count)
        _EVENTS.appendleft(
            {
                "type": "job",
                "kind": payload.get("kind"),
                "status": status,
                "duration_ms": duration,
                "count": count,
                "ts": time.time(),
            }
        )


def record_magnet_search(payload: dict[str, Any]) -> None:
    event = {
        "ts": time.time(),
        "kind": "magnet_search",
        "title": str(payload.get("title") or "")[:120],
        "total_ms": int(payload.get("total_ms") or 0),
        "candidates": int(payload.get("candidates") or 0),
        "matched": int(payload.get("matched") or 0),
        "early_stop": bool(payload.get("early_stop") or False),
        "cache_hit": bool(payload.get("cache_hit") or False),
    }
    with _LOCK:
        _EVENTS.appendleft(event)
        _COUNTERS["magnet_searches"] = int(_COUNTERS.get("magnet_searches", 0) or 0) + 1
        _COUNTERS["magnet_ms_sum"] = int(_COUNTERS.get("magnet_ms_sum", 0) or 0) + event["total_ms"]
        if event["early_stop"]:
            _COUNTERS["magnet_early_stops"] = int(_COUNTERS.get("magnet_early_stops", 0) or 0) + 1
        if event["cache_hit"]:
            _COUNTERS["magnet_cache_hits"] = int(_COUNTERS.get("magnet_cache_hits", 0) or 0) + 1
        _SAMPLES.setdefault("magnet_ms", __import__("collections").deque(maxlen=120)).append(event["total_ms"])


def record_index_query(payload: dict[str, Any]) -> None:
    path = str(payload.get("path") or "recent")
    with _LOCK:
        _COUNTERS["index_queries"] = int(_COUNTERS.get("index_queries", 0) or 0) + 1
        key = {"fts": "index_fts_hits", "like": "index_like_hits"}.get(path, "index_recent_hits")
        _COUNTERS[key] = int(_COUNTERS.get(key, 0) or 0) + 1
        _EVENTS.appendleft({"ts": time.time(), "kind": "index_query", "path": path, "count": int(payload.get("count") or 0)})
