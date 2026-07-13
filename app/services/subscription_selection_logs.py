from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription_matching import _result_debug_payload, _result_skip_reason, _skip_reason_summary
from app.services.subscription_resource_ops import _unmatched_results


def log_unmatched_results(
    facade: Any,
    subscription: dict,
    results: list[SearchResult],
    matched: list[SearchResult],
    *,
    source_label: str,
    level_when_no_match: str = "info",
) -> None:
    skipped = len(results) - len(matched)
    if skipped <= 0:
        return
    skipped_results = _unmatched_results(results, matched)
    reason_summary = _skip_reason_summary(subscription, skipped_results)
    add_log(
        level_when_no_match if not matched else "debug",
        "subscription",
        _unmatched_message(source_label, reason_summary),
        {
            "id": int(subscription["id"]),
            "skipped": skipped,
            "samples": [_unmatched_sample(subscription, result) for result in skipped_results[:3]],
        },
    )


def log_unmatched_fallback_groups(
    facade: Any,
    subscription: dict,
    total: int,
    group_matches: list[tuple[dict[str, Any], list[SearchResult], list[SearchResult]]],
) -> None:
    matched_count = sum(len(matched_results) for _, _, matched_results in group_matches)
    skipped = total - matched_count
    if skipped <= 0:
        return
    skipped_results = [
        result
        for _, group_results, matched_results in group_matches
        for result in _unmatched_results(group_results, matched_results)
    ]
    reason_summary = _skip_reason_summary(subscription, skipped_results)
    add_log("debug", "subscription", _unmatched_message("订阅源/磁力", reason_summary), {"id": int(subscription["id"]), "skipped": skipped})


def _unmatched_message(source_label: str, reason_summary: str) -> str:
    if reason_summary:
        return f"{source_label}结果未匹配订阅条件，已跳过（{reason_summary}）"
    return f"{source_label}结果未匹配订阅条件，已跳过"


def _unmatched_sample(subscription: dict, result: SearchResult) -> dict[str, Any]:
    payload = _result_debug_payload(result)
    payload["reason"] = _result_skip_reason(subscription, result)
    return payload
