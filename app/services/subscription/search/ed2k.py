"""
ed2k link search and attachment for Telegram subscriptions.

This module handles ed2k links independently from the 115 share pipeline.
Each ed2k link is a single-episode resource identified by its filename.
All matching ed2k links from all messages are processed without the
1-result limit that applies to 115 share links in the fast search stage.
"""

from __future__ import annotations

from typing import Any

from app.db import add_log, db, utc_now
from app.services.subscription.search.discovery import search_telegram_history
from app.services.adapters.telegram.models import TelegramSearchSharedState
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.matching import (
    episode_keys_from_text_for_subscription,
    missing_episode_keys,
    subscription_search_title,
)
from app.services.subscription.resource.resources import (
    existing_resource_rows as _existing_resource_rows,
    resource_dedupe_key as _resource_dedupe_key,
    resource_status_is_effective as _resource_status_is_effective,
)
from app.services.subscription.resource.guard import resource_allowed_for_subscription
from app.services.link.downloads import is_valid_download_link


def _is_ed2k_link(result: SearchResult) -> bool:
    """Check if a search result is an ed2k link."""
    url = str(getattr(result, "url", "") or "")
    return url.casefold().startswith("ed2k://")


def _ed2k_match_text(result: SearchResult) -> str:
    """Return the text for episode matching from an ed2k result.

    ed2k links carry episode info in the filename (title).  The
    message context (header) must be ignored because it typically
    describes the full pack range, not the individual episode.
    """
    return str(getattr(result, "title", "") or "")


def _resource_exists(
    conn,
    subscription_id: int,
    result: SearchResult,
    existing_rows: list[dict[str, Any]],
) -> str | None:
    """Check whether an ed2k resource already exists for this subscription.

    Uses the ed2k URL as the dedup key.  Unlike the 115 pipeline, we do
    NOT perform title-similarity matching here — each ed2k link has a
    unique URL per episode, and the filename already encodes the episode.
    """
    candidate_key = _resource_dedupe_key(result.url)
    if candidate_key:
        for row in existing_rows:
            if not _resource_status_is_effective(row.get("status")):
                continue
            if _resource_dedupe_key(row.get("url") or "") == candidate_key:
                return f"same_url"
    return None


async def search_and_attach_ed2k(
    facade,
    subscription: dict,
    search_title: str | None = None,
    *,
    telegram_results: list[SearchResult] | None = None,
) -> tuple[list[dict], list[SearchResult], dict[str, Any]]:
    """Search Telegram for ed2k links, match against the subscription, and
    save every matching resource.

    Unlike the 115 share pipeline, this function does NOT limit results:
    * No fast‑search 1‑result limit — all ed2k links from all messages are
      processed.
    * Episode info is parsed from the filename (title) only, never from the
      message context.
    * Each ed2k link is treated as a single‑episode resource.

    Args:
        facade: Application facade (may be None).
        subscription: Subscription dict.
        search_title:  Optional search title; auto‑detected when omitted.
        telegram_results:  Optional pre‑fetched Telegram results; when
            provided the search is skipped (avoids a redundant network call).

    Returns:
        ``(created_resources, matched_results, summary_dict)``
    """
    subscription_id = int(subscription["id"])
    media_type = subscription.get("media_type", "")
    if media_type != "tv":
        add_log("debug",
            "subscription",
            "ed2k 搜索仅支持电视剧订阅，已跳过",
            {"id": subscription_id, "media_type": media_type},
        )
        return [], [], {"created": 0, "matched": 0}

    # ── Step 1: fetch Telegram search results ──────────────────────
    if telegram_results is None:
        if search_title is None:
            search_title = subscription_search_title(subscription)
        telegram_results = await search_telegram_history(
            facade,
            subscription,
            search_title,
            shared_state=TelegramSearchSharedState(),
        )

    # ── Step 2: filter for ed2k links only ─────────────────────────
    ed2k_results: list[SearchResult] = []
    for result in telegram_results:
        if not _is_ed2k_link(result):
            continue
        title = str(getattr(result, "title", "") or "")
        if not title:
            continue
        ed2k_results.append(result)

    if not ed2k_results:
        add_log("debug",
            "subscription",
            "ed2k 搜索未找到任何 ed2k 链接",
            {"id": subscription_id, "total_results": len(telegram_results)},
        )
        return [], [], {"created": 0, "matched": 0}

    add_log("debug",
        "subscription",
        "ed2k 搜索找到链接",
        {"id": subscription_id, "count": len(ed2k_results)},
    )

    # ── Step 3: match and save ─────────────────────────────────────
    created: list[dict] = []
    matched: list[SearchResult] = []
    duplicate_count = 0
    save_failed_count = 0

    with db() as conn:
        existing_rows = _existing_resource_rows(conn, subscription_id)
        missing = set(missing_episode_keys(subscription) or [])
        for result in ed2k_results:
            # Parse episode from filename (title) only.
            text = _ed2k_match_text(result)
            episodes = episode_keys_from_text_for_subscription(subscription, text)

            # Skip if episode is not missing.
            if episodes and missing and not (episodes & missing):
                add_log("debug",
                    "subscription",
                    "ed2k 剧集不在缺集范围，跳过",
                    {
                        "id": subscription_id,
                        "title": text[:120],
                        "episodes": [f"{s}x{e}" for s, e in sorted(episodes)],
                    },
                )
                continue

            # Validate the link.
            if not is_valid_download_link(result.url):
                add_log("debug",
                    "subscription",
                    "ed2k 链接格式无效，跳过",
                    {"id": subscription_id, "url": str(result.url or "")[:160]},
                )
                continue

            # Guard check.
            if not resource_allowed_for_subscription(subscription, result, scope="save"):
                save_failed_count += 1
                continue

            # Duplicate check.
            if _resource_exists(conn, subscription_id, result, existing_rows):
                duplicate_count += 1
                matched.append(result)
                continue

            # Save.
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO resources
                    (subscription_id, source, title, url, message_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    result.source,
                    result.title,
                    result.url,
                    result.message_id,
                    utc_now(),
                    utc_now(),
                ),
            )
            if cursor.rowcount == 0:
                save_failed_count += 1
                continue

            saved = {**result.__dict__, "resource_id": cursor.lastrowid}
            created.append(saved)
            matched.append(result)
            existing_rows.insert(0, {"title": result.title, "url": result.url, "status": "pending"})

        conn.execute(
            "UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), subscription_id),
        )

    summary = {
        "created": len(created),
        "matched": len(matched),
        "duplicates": duplicate_count,
        "save_failed": save_failed_count,
    }

    if created:
        add_log("info",
            "subscription",
            "发现新的 ed2k 资源链接",
            {"id": subscription_id, "count": len(created)},
        )

    return created, matched, summary