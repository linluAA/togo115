from __future__ import annotations

from app.db import add_log
from app.schemas import SearchRequest
from app.services.adapters.telegram import TelegramClientAdapter
from app.services.sources.rss_torznab import RssTorznabAdapter
from app.services.subscription_crud import get_subscription
from app.services.subscription_resource_ops import _best_fallback_result, _matching_results


def subscription_like_from_payload(payload: SearchRequest) -> dict:
    existing = get_subscription(payload.subscription_id) if payload.subscription_id else None
    if existing:
        return existing
    return {
        "title": payload.title,
        "keywords": payload.keywords,
        "media_type": payload.media_type,
        "tmdb_id": payload.tmdb_id,
        "release_year": payload.release_year,
        "tmdb_total_count": payload.tmdb_total_count or 0,
        "tmdb_seasons": payload.tmdb_seasons,
        "emby_episode_keys": payload.emby_episode_keys,
        "emby_count": payload.emby_count,
        "in_library": payload.in_library,
        "quality_rules": payload.quality_rules,
    }


def search_title_from_payload(payload: SearchRequest) -> str:
    search_title = payload.title
    if payload.release_year and str(payload.release_year) not in search_title:
        search_title = f"{search_title} {payload.release_year}"
    return search_title


async def manual_search_resources(payload: SearchRequest) -> dict:
    return await _manual_search_resources(payload)


async def _manual_search_resources(payload: SearchRequest) -> dict:
    add_log("info", "search", "手动搜索开始", payload.model_dump())
    subscription_like = subscription_like_from_payload(payload)
    search_title = search_title_from_payload(payload)
    try:
        telegram_results = await TelegramClientAdapter().search_history(search_title, payload.keywords)
    except Exception as exc:
        telegram_results = []
        add_log("warning", "search", "手动搜索 Telegram 历史失败，继续尝试订阅源/磁力", {"title": payload.title, "error": str(exc)})
    matched = _matching_results(subscription_like, telegram_results)
    if not matched:
        try:
            source_groups = await RssTorznabAdapter().search_history_by_priority_until_match(
                search_title,
                payload.keywords,
                lambda result: bool(_matching_results(subscription_like, [result])),
            )
        except Exception as exc:
            source_groups = []
            add_log("warning", "search", "手动搜索订阅源/磁力失败", {"title": payload.title, "error": str(exc)})
        for group in source_groups:
            fallback_matches = _matching_results(subscription_like, list(group["results"]))
            best_result = _best_fallback_result(fallback_matches, subscription_like)
            if best_result:
                matched = [best_result]
                break
    return {"results": [result.__dict__ for result in matched], "count": len(matched)}
