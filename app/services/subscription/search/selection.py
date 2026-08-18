from __future__ import annotations

from typing import Any

from app.db import add_log, db, utc_now
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.candidate_decision import decide_resource_candidate
from app.services.subscription.resource.ops import (
    existing_resource_rows,
    fallback_result_candidates,
    insert_resource_safely,
    matching_results,
)
from app.services.subscription.search.selection_fallback import (
    attach_fallback_results_until_delivered,
    attach_first_fallback_result,
    match_fallback_groups,
)
from app.services.search_metrics import record_attach_outcome
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
    # Filter out ed2k links — they are handled by the independent ed2k search
    # module (search_and_attach_ed2k) which has no 1-result limit.
    filtered = [r for r in results if not str(getattr(r, "url", "") or "").casefold().startswith("ed2k://")]
    raw_matched = matching_results(subscription, filtered)
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

    ordered = fallback_result_candidates(raw_matched, subscription)
    matched: list[SearchResult] = []
    created: list[dict] = []
    duplicate_count = 0
    save_failed_count = 0

    with db() as conn:
        existing_rows = existing_resource_rows(conn, subscription_id)
        covered_missing: set[tuple[int, int]] = set()
        bare_pack_saved = False
        for result in ordered:
            if covered_missing and _result_missing_already_covered(
                subscription, result, covered_missing, bare_pack_saved=bare_pack_saved
            ):
                continue
            outcome = _save_telegram_result(conn, subscription, result, existing_rows)
            if outcome == "created":
                matched.append(result)
                created.append(getattr(result, "_saved_item"))
                covered_missing |= _missing_coverage_for_result(subscription, result)
                if not covered_missing:
                    bare_pack_saved = True
                    break
                continue
            if outcome == "duplicate":
                duplicate_count += 1
                matched.append(result)
                continue
            save_failed_count += 1
        conn.execute(
            "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription_id),
        )

    log_unmatched_results(facade, subscription, results, matched, source_label="TG 历史搜索")
    available_matched = len(created) + int(duplicate_count)
    summary = {
        "raw_matched": len(raw_matched),
        "available_matched": available_matched,
        "created": len(created),
        "duplicates": duplicate_count,
        "save_failed": save_failed_count,
        "from_index": any(
            str(getattr(result, "source", "") or "") == "TelegramIndex"
            or str(getattr(result, "source", "") or "").startswith("TelegramIndex:")
            for result in results
        ),
    }
    _log_telegram_attach_summary(subscription_id, summary)
    record_attach_outcome(
        {
            "id": subscription_id,
            "created": summary.get("created", 0),
            "duplicates": summary.get("duplicates", 0),
            "save_failed": summary.get("save_failed", 0),
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
    except Exception as exc:
        add_log(
            "warning",
            "subscription",
            "资源候选决策异常，跳过覆盖范围计算",
            {
                "id": subscription.get("id"),
                "title": str(getattr(result, "title", "") or "")[:120],
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        return set()
    return set(decision.missing_coverage or ())


def _result_missing_already_covered(
    subscription: dict,
    result: SearchResult,
    covered_missing: set[tuple[int, int]],
    *,
    bare_pack_saved: bool = False,
) -> bool:
    coverage = _missing_coverage_for_result(subscription, result)
    if coverage:
        return coverage.issubset(covered_missing)
    return bare_pack_saved


__all__ = [
    "attach_fallback_results_until_delivered",
    "attach_first_fallback_result",
    "attach_telegram_results",
    "log_unmatched_fallback_groups",
    "log_unmatched_results",
    "match_fallback_groups",
]