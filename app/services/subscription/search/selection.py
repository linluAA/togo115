from __future__ import annotations

import time
from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_UNAVAILABLE, SHARE_UNKNOWN
from app.services.subscription.search.share115_cache import process_115_cache
from app.services.subscription.match.candidate_decision import decide_resource_candidate
from app.services.subscription.resource.ops import (
    existing_resource_rows,
    fallback_result_candidates,
    insert_resource_safely,
    matching_results,
    resource_already_exists,
)
from app.services.subscription.search.selection_fallback import (
    attach_fallback_results_until_delivered,
    attach_first_fallback_result,
    match_fallback_groups,
)
from app.services.search_metrics import record_115_validation, record_attach_outcome
from app.services.subscription.search.selection_logs import (
    log_unmatched_fallback_groups,
    log_unmatched_results,
)
from app.services.subscription.search.selection_telegram import (
    _log_telegram_attach_summary,
    _save_telegram_result,
)


async def attach_telegram_results(
    facade,
    subscription: dict,
    results: list[SearchResult],
) -> tuple[list[dict], list[SearchResult], dict[str, Any]]:
    subscription_id = int(subscription["id"])
    raw_matched = matching_results(subscription, results)
    if not raw_matched and results:
        samples = [
            {
                "title": str(getattr(result, "title", "") or "")[:120],
                "source": str(getattr(result, "source", "") or "")[:80],
                "url": str(getattr(result, "url", "") or "")[:160],
                "message_id": getattr(result, "message_id", None),
            }
            for result in results[:3]
        ]
        add_log("debug",
            "subscription",
            "TG 已提取链接但标题上下文未命中订阅，已跳过以避免错误投递",
            {
                "id": subscription_id,
                "title": subscription.get("title"),
                "candidates": len(results),
                "samples": samples,
            },
        )
    # Progressive validation with duplicate fall-through:
    # order by missing-episode coverage, validate 115 with prefetch, skip expired and
    # already-saved packs. Keep creating non-overlapping packs for remaining missing eps.
    ordered = fallback_result_candidates(raw_matched, subscription)
    matched: list[SearchResult] = []
    recheck_results: list[SearchResult] = []
    validation_started = time.perf_counter()
    validation_report: dict[str, Any] = {"checked_115": 0, "expired_115": 0, "recheck_115": 0}
    created: list[dict] = []
    duplicate_count = 0
    save_failed_count = 0
    recheck_saved_count = 0
    # Prefetch 115 states for top candidates with bounded concurrency, then save sequentially
    # so "first created wins" ordering stays deterministic.
    share_cache = process_115_cache() if ordered else None
    prefaced_states: dict[str, str] = {}
    if share_cache is not None and ordered:
        probe_urls = [
            str(getattr(result, "url", "") or "")
            for result in ordered[:16]
            if PAN115_URL_RE.match(str(getattr(result, "url", "") or ""))
        ]
        if probe_urls:
            prefaced_states = await share_cache.availability_many(probe_urls)

    with db() as conn:
        existing_rows = existing_resource_rows(conn, subscription_id)
        covered_missing: set[tuple[int, int]] = set()
        for result in ordered:
            if covered_missing and _result_missing_already_covered(subscription, result, covered_missing):
                continue
            url = str(getattr(result, "url", "") or "")
            mark_recheck = False
            if share_cache is not None and PAN115_URL_RE.match(url):
                state = prefaced_states.get(url)
                if state is None:
                    state = await share_cache.availability(url)
                validation_report["checked_115"] += 1
                if state == SHARE_UNAVAILABLE:
                    validation_report["expired_115"] += 1
                    add_log("debug",
                        "subscription",
                        "115 分享链接已失效，跳过保存和投递",
                        {
                            "url": url,
                            "title": str(getattr(result, "title", "") or "")[:120],
                            "source": getattr(result, "source", ""),
                        },
                    )
                    continue
                if state == SHARE_UNKNOWN:
                    validation_report["recheck_115"] += 1
                    mark_recheck = True
                    recheck_results.append(result)
                    add_log(
                        "warning",
                        "subscription",
                        "115 分享链接有效性待复检，先继续投递",
                        {
                            "url": url,
                            "title": str(getattr(result, "title", "") or "")[:120],
                            "source": getattr(result, "source", ""),
                        },
                    )
            outcome = _save_telegram_result(
                conn,
                subscription,
                result,
                existing_rows,
                mark_recheck=mark_recheck,
            )
            if outcome == "created":
                matched.append(result)
                created.append(getattr(result, "_saved_item"))
                covered_missing |= _missing_coverage_for_result(subscription, result)
                if mark_recheck:
                    recheck_saved_count += 1
                # Bare (no episode) packs already cover unknown scope; stop to avoid multi-save.
                if not covered_missing:
                    break
                continue
            if outcome == "duplicate":
                duplicate_count += 1
                matched.append(result)
                continue
            save_failed_count += 1
        if not created:
            for result in recheck_results:
                if covered_missing and _result_missing_already_covered(subscription, result, covered_missing):
                    continue
                outcome = _save_telegram_result(conn, subscription, result, existing_rows, mark_recheck=True)
                if outcome == "created":
                    matched.append(result)
                    created.append(getattr(result, "_saved_item"))
                    covered_missing |= _missing_coverage_for_result(subscription, result)
                    recheck_saved_count += 1
                    if not covered_missing:
                        break
                    continue
                if outcome == "duplicate":
                    duplicate_count += 1
                else:
                    save_failed_count += 1
        conn.execute(
            "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription_id),
        )

    validation_report = {**validation_report, "115_ms": int((time.perf_counter() - validation_started) * 1000)}

    log_unmatched_results(facade, subscription, results, matched, source_label="TG 历史搜索")
    available_matched = len(created) + int(duplicate_count)
    summary = {
        "raw_matched": len(raw_matched),
        "available_matched": available_matched,
        "created": len(created),
        "duplicates": duplicate_count,
        "save_failed": save_failed_count,
        "recheck_saved": recheck_saved_count,
        "from_index": any(
            str(getattr(result, "source", "") or "") == "TelegramIndex"
            or str(getattr(result, "source", "") or "").startswith("TelegramIndex:")
            for result in results
        ),
        **validation_report,
    }
    add_log("debug",
        "subscription",
        "TG 搜索指标",
        {
            "id": subscription_id,
            "115_ms": summary.get("115_ms", 0),
            "checked_115": summary.get("checked_115", 0),
            "expired_115": summary.get("expired_115", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "raw_matched": summary.get("raw_matched", 0),
            "created": summary.get("created", 0),
            "from_index": summary.get("from_index", False),
        },
    )
    _log_telegram_attach_summary(subscription_id, summary)
    record_115_validation(
        {
            "id": subscription_id,
            "115_ms": summary.get("115_ms", 0),
            "checked_115": summary.get("checked_115", 0),
            "expired_115": summary.get("expired_115", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "created": summary.get("created", 0),
            "from_index": summary.get("from_index", False),
        }
    )
    record_attach_outcome(
        {
            "id": subscription_id,
            "created": summary.get("created", 0),
            "duplicates": summary.get("duplicates", 0),
            "expired_115": summary.get("expired_115", 0),
            "save_failed": summary.get("save_failed", 0),
            "recheck_115": summary.get("recheck_115", 0),
            "raw_matched": summary.get("raw_matched", 0),
            "candidates": len(results),
            "from_index": summary.get("from_index", False),
        }
    )
    if results and not created:
        add_log("debug",
            "subscription",
            "TG 提取结果未形成新投递",
            {
                "id": subscription_id,
                "title": subscription.get("title"),
                "candidates": len(results),
                "raw_matched": summary.get("raw_matched", 0),
                "available_matched": summary.get("available_matched", 0),
                "created": summary.get("created", 0),
                "duplicates": summary.get("duplicates", 0),
                "expired_115": summary.get("expired_115", 0),
                "recheck_115": summary.get("recheck_115", 0),
                "save_failed": summary.get("save_failed", 0),
                "from_index": summary.get("from_index", False),
                "samples": [
                    {
                        "title": str(getattr(result, "title", "") or "")[:120],
                        "source": str(getattr(result, "source", "") or "")[:80],
                        "url": str(getattr(result, "url", "") or "")[:160],
                    }
                    for result in results[:3]
                ],
            },
        )
    return created, matched, summary




def _missing_coverage_for_result(subscription: dict, result: SearchResult) -> set[tuple[int, int]]:
    try:
        decision = decide_resource_candidate(subscription, result)
    except Exception:
        return set()
    return set(decision.missing_coverage or ())


def _result_missing_already_covered(
    subscription: dict,
    result: SearchResult,
    covered_missing: set[tuple[int, int]],
) -> bool:
    coverage = _missing_coverage_for_result(subscription, result)
    if coverage:
        return coverage.issubset(covered_missing)
    # No explicit episode coverage: treat as whole-scope pack and skip once anything was created.
    return bool(covered_missing)


__all__ = [
    "attach_fallback_results_until_delivered",
    "attach_first_fallback_result",
    "attach_telegram_results",
    "log_unmatched_fallback_groups",
    "log_unmatched_results",
    "match_fallback_groups",
]
