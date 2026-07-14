from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.subscription.search.discovery import search_fallback_sources, search_telegram_history
from app.services.subscription.match.matching import _subscription_search_title
from app.services.subscription.search.selection import (
    attach_fallback_results_until_delivered,
    attach_first_fallback_result,
    attach_telegram_results,
    log_unmatched_fallback_groups,
    match_fallback_groups,
)


async def _search_telegram_first(subscription: dict, incremental_telegram: bool) -> tuple[list[dict], list, dict[str, Any]]:
    search_title = _subscription_search_title(subscription)
    if not incremental_telegram:
        created, matches, summary = await _run_telegram_search_stage(subscription, search_title, fast=True)
        if created:
            return created, matches, summary
        if summary.get("raw_matched") and not _telegram_summary_needs_full_retry(summary):
            return created, matches, summary
    return await _run_telegram_search_stage(subscription, search_title, fast=False, incremental=incremental_telegram)


async def _run_telegram_search_stage(
    subscription: dict,
    search_title: str,
    *,
    fast: bool,
    incremental: bool = False,
) -> tuple[list[dict], list, dict[str, Any]]:
    telegram_results = await search_telegram_history(None, subscription, search_title, incremental=incremental, fast=fast)
    created, telegram_matches, summary = await attach_telegram_results(None, subscription, telegram_results)
    _log_telegram_stage_result(subscription, created, telegram_matches, summary, fast=fast)
    return created, telegram_matches, summary


def _telegram_summary_needs_full_retry(summary: dict[str, Any]) -> bool:
    if summary.get("from_index") and not summary.get("created"):
        return True
    return bool(summary.get("expired_115") or summary.get("recheck_115") or summary.get("save_failed"))


def _log_telegram_stage_result(
    subscription: dict,
    created: list[dict],
    telegram_matches: list,
    summary: dict[str, Any],
    *,
    fast: bool,
) -> None:
    stage = "快速" if fast else "历史"
    if created:
        add_log(
            "info",
            "subscription",
            f"TG {stage}搜索已找到可用资源，跳过订阅源/磁力搜索",
            {"id": subscription["id"], "count": len(created)},
        )
        add_log("info", "subscription", "发现新的 TG 资源链接", {"id": subscription["id"], "count": len(created)})
    elif telegram_matches:
        add_log(
            "info",
            "subscription",
            f"TG {stage}搜索找到资源但没有新增保存，已按原因决定是否继续兜底",
            {"id": subscription["id"], **summary},
        )


def _telegram_should_skip_fallback(summary: dict[str, Any]) -> bool:
    """Skip fallback only when Telegram found usable resources that are already known."""
    available = int(summary.get("available_matched") or 0)
    if available <= 0:
        return False
    if int(summary.get("created") or 0) > 0:
        return True
    if int(summary.get("expired_115") or 0) > 0:
        return False
    if int(summary.get("save_failed") or 0) > 0:
        return False
    return int(summary.get("duplicates") or 0) == available


async def _search_fallback_when_needed(subscription: dict, deliver_func=None) -> list[dict]:
    search_title = _subscription_search_title(subscription)
    fallback_groups = await search_fallback_sources(None, subscription, search_title)
    fallback_total, fallback_matches = match_fallback_groups(None, subscription, fallback_groups)
    if deliver_func is None:
        fallback_created = attach_first_fallback_result(None, subscription, fallback_matches)
    else:
        fallback_created = await attach_fallback_results_until_delivered(None, subscription, fallback_matches, deliver_func)
    log_unmatched_fallback_groups(None, subscription, fallback_total, fallback_matches)
    if fallback_created:
        add_log("info", "subscription", "订阅源/磁力发现新的资源链接", {"id": subscription["id"], "count": len(fallback_created)})
    return fallback_created
