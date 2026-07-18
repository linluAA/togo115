#!/usr/bin/env python3
"""P3: promote selected cross-boundary private symbols to public names.

Renames definitions and updates imports/usages across the repo.
Keeps thin private aliases only when tests still reference the old name
via explicit private import (tests will be updated too).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# private -> public
RENAMES: dict[str, str] = {
    # crud
    "_active_subscriptions": "active_subscriptions",
    "_mark_subscription_checked": "mark_subscription_checked",
    "_duplicate_subscription": "duplicate_subscription",
    # episode
    "_missing_episode_keys": "missing_episode_keys",
    "_episode_keys_from_text_for_subscription": "episode_keys_from_text_for_subscription",
    "_json_episode_key": "json_episode_key",
    "_tmdb_seasons_from_detail": "tmdb_seasons_from_detail",
    "_chinese_number_to_int": "chinese_number_to_int",
    # library
    "_enrich_subscriptions_with_health": "enrich_subscriptions_with_health",
    "_mark_completed_subscription": "mark_completed_subscription",
    "_subscription_should_hide": "subscription_should_hide",
    "_library_snapshot_or_none": "library_snapshot_or_none",
    # match
    "_compact_match_text": "compact_match_text",
    "_extra_search_keywords": "extra_search_keywords",
    "_normalize_quality_rules": "normalize_quality_rules",
    "_result_debug_payload": "result_debug_payload",
    "_result_skip_reason": "result_skip_reason",
    "_skip_reason_summary": "skip_reason_summary",
    "_subscription_release_year": "subscription_release_year",
    "_subscription_search_title": "subscription_search_title",
    "_result_text": "result_text",
    "_years_from_text": "years_from_text",
    "_title_without_year": "title_without_year",
    "_result_is_fallback_source": "result_is_fallback_source",
    "_result_priority": "result_priority",
    # resource
    "_fallback_blocked_by_primary_resource": "fallback_blocked_by_primary_resource",
    "_unmatched_results": "unmatched_results",
    "_matching_results": "matching_results",
    "_best_fallback_result": "best_fallback_result",
    "_fallback_result_candidates": "fallback_result_candidates",
    "_resource_already_exists": "resource_already_exists",
    "_existing_resource_rows": "existing_resource_rows",
    "_insert_resource_safely": "insert_resource_safely",
    "_results_may_match_subscription": "results_may_match_subscription",
    "_subscription_115_resources": "subscription_115_resources",
    # delivery
    "_deliver_resource_url": "deliver_resource_url",
    "_delivery_failed_status": "delivery_failed_status",
}


def rename_in_text(text: str) -> str:
    # longest first
    for old in sorted(RENAMES.keys(), key=len, reverse=True):
        new = RENAMES[old]
        # word-boundary-ish for python identifiers
        text = re.sub(rf"(?<![\w]){re.escape(old)}(?![\w])", new, text)
    return text


def main() -> None:
    paths = [
        * (ROOT / "app").rglob("*.py"),
        * (ROOT / "tests").rglob("*.py"),
    ]
    changed = 0
    for path in paths:
        if "scripts/" in str(path):
            continue
        original = path.read_text(encoding="utf-8")
        updated = rename_in_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"updated {path.relative_to(ROOT)}")
    print(f"files changed: {changed}")


if __name__ == "__main__":
    main()
