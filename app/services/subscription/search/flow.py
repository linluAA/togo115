from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.subscription.search.discovery import search_fallback_sources, search_telegram_history
from app.services.adapters.telegram.models import TelegramSearchSharedState
from app.services.subscription.match.matching import subscription_search_title
from app.services.subscription.search.selection import (
    attach_fallback_results_until_delivered,
    attach_first_fallback_result,
    attach_telegram_results,
    log_unmatched_fallback_groups,
    match_fallback_groups,
)


async def _search_telegram_first(subscription: dict, incremental_telegram: bool) -> tuple[list[dict], list, dict[str, Any]]:
    search_title = subscription_search_title(subscription)
    shared_state = TelegramSearchSharedState()
    if not incremental_telegram:
        created, matches, summary = await _run_telegram_search_stage(
            subscription,
            search_title,
            fast=True,
            shared_state=shared_state,
        )
        if created:
            return created, matches, summary
        # Fast stage already resolved the library state for this subscription.
        # Skip full TG search when there is nothing new to fetch remotely.
        if _telegram_should_skip_full_after_fast(summary, subscription):
            add_log("debug",
                "subscription",
                "TG 快速搜索已足够，跳过完整历史搜索",
                {
                    "id": subscription.get("id"),
                    "title": subscription.get("title"),
                    "raw_matched": summary.get("raw_matched", 0),
                    "duplicates": summary.get("duplicates", 0),
                    "expired_115": summary.get("expired_115", 0),
                    "from_index": summary.get("from_index", False),
                },
            )
            return created, matches, summary
        if summary.get("raw_matched") and not _telegram_summary_needs_full_retry(summary, subscription):
            return created, matches, summary
        # Targeted remote recheck only for sources that produced index hits.
        if summary.get("from_index") and not summary.get("created"):
            shared_state.force_remote = True
            shared_state.set_preferred_sources_from_results(matches or [])
            # If attach never saw matched results, fall back to any recent index hits
            # recorded in shared state via seen sources is unavailable; prefer full
            # force_remote across all dialogs only when no preferred source known.
            if not shared_state.preferred_sources:
                # matches empty: use summary samples not available; keep force_remote global.
                pass
            add_log(
                "debug",
                "subscription",
                "TG 索引命中未形成新投递，改为定点远程复核",
                {
                    "id": subscription.get("id"),
                    "preferred_sources": list(shared_state.preferred_sources),
                    "force_remote": True,
                },
            )
    return await _run_telegram_search_stage(
        subscription,
        search_title,
        fast=False,
        incremental=incremental_telegram,
        shared_state=shared_state,
    )


async def _run_telegram_search_stage(
    subscription: dict,
    search_title: str,
    *,
    fast: bool,
    incremental: bool = False,
    shared_state: TelegramSearchSharedState | None = None,
) -> tuple[list[dict], list, dict[str, Any]]:
    telegram_results = await search_telegram_history(
        None,
        subscription,
        search_title,
        incremental=incremental,
        fast=fast,
        shared_state=shared_state,
    )
    # Remember which dialogs produced index hits for later targeted recheck.
    if shared_state is not None and telegram_results:
        shared_state.set_preferred_sources_from_results(telegram_results)
    created, telegram_matches, summary = await attach_telegram_results(None, subscription, telegram_results)
    _log_telegram_stage_result(subscription, created, telegram_matches, summary, fast=fast)
    return created, telegram_matches, summary


def _telegram_should_skip_full_after_fast(summary: dict[str, Any], subscription: dict | None = None) -> bool:
    """Skip full TG history when fast stage already settled the outcome.

    Cases:
    - created resources: full search is unnecessary
    - matched only duplicates when the library no longer has missing episodes
    - index-only pure duplicates with remaining missing episodes still go full/remote
    - expired/recheck/save_failed still need full or fallback path
    """
    if int(summary.get("created") or 0) > 0:
        return True
    if int(summary.get("expired_115") or 0) > 0:
        return False
    if int(summary.get("recheck_115") or 0) > 0:
        return False
    if int(summary.get("save_failed") or 0) > 0:
        return False
    available = int(summary.get("available_matched") or 0)
    duplicates = int(summary.get("duplicates") or 0)
    raw_matched = int(summary.get("raw_matched") or 0)
    pure_duplicates = (raw_matched > 0 and duplicates >= raw_matched) or (
        available > 0 and duplicates >= available and int(summary.get("created") or 0) == 0
    )
    if not pure_duplicates:
        return False
    # Index hits are a partial view. If the subscription still misses episodes,
    # keep scanning full/remote history for newer packs.
    if summary.get("from_index") and _subscription_has_missing_episodes(subscription):
        return False
    return True


def _subscription_has_missing_episodes(subscription: dict | None) -> bool:
    if not subscription or subscription.get("media_type") != "tv":
        return False
    try:
        from app.services.subscription.episode.parser import missing_episode_keys

        return bool(missing_episode_keys(subscription))
    except Exception:
        # Fail open: prefer another search pass over silently missing new packs.
        return True


def _telegram_summary_needs_full_retry(summary: dict[str, Any], subscription: dict | None = None) -> bool:
    # Index hits that failed to create still deserve a targeted remote recheck.
    if summary.get("from_index") and not summary.get("created"):
        # Pure duplicates without remaining missing episodes do not need remote recheck.
        if _telegram_should_skip_full_after_fast(summary, subscription):
            return False
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
            "debug",
            "subscription",
            f"TG {stage}搜索找到资源但没有新增保存，已按原因决定是否继续兜底",
            {"id": subscription["id"], **summary},
        )


def _telegram_should_skip_fallback(summary: dict[str, Any], subscription: dict | None = None) -> bool:
    """Skip fallback only when Telegram found usable resources that are already known.

    If the subscription still misses episodes, keep RSS/magnet fallback even when
    Telegram only produced duplicates of older packs.
    """
    available = int(summary.get("available_matched") or 0)
    if available <= 0:
        return False
    if int(summary.get("created") or 0) > 0:
        return True
    if int(summary.get("expired_115") or 0) > 0:
        return False
    if int(summary.get("save_failed") or 0) > 0:
        return False
    if int(summary.get("duplicates") or 0) != available:
        return False
    if _subscription_has_missing_episodes(subscription):
        return False
    return True


async def _search_fallback_when_needed(subscription: dict, deliver_func=None) -> list[dict]:
    search_title = subscription_search_title(subscription)
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
