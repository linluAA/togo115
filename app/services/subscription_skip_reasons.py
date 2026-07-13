from __future__ import annotations

from collections import Counter

from app.db import add_log
from app.services.subscription_episode_parser import (
    _all_tmdb_episode_keys,
    _episode_keys_from_text_for_subscription,
    _missing_episode_keys,
)
from app.services.subscription_identity import (
    _release_year_matches,
    _result_title_identity_conflicts,
    _subscription_match_text,
    _subscription_required_terms,
    _term_in_text,
    _title_term_in_text,
    _tmdb_ids_from_text,
)
from app.services.subscription_quality import _quality_rule_skip_reason
from app.services.subscription_result_utils import _result_debug_payload, _result_text
from app.services.subscription_text_utils import _compact_match_text
from app.services.types import SearchResult


def _result_skip_reason(subscription: dict, result: SearchResult, *extra_texts: str) -> str:
    text = _subscription_match_text(result, *extra_texts)
    if not text:
        return "文本为空"
    raw_haystack = text.casefold()
    compact_haystack = _compact_match_text(text)
    title_term, keyword_terms = _subscription_required_terms(subscription)
    if _result_title_identity_conflicts(subscription, result):
        return "资源标题不匹配"
    if not _release_year_matches(subscription, result, text, *extra_texts):
        return "年份不匹配"
    tmdb_title_reason = _tmdb_title_skip_reason(subscription, text, title_term)
    if tmdb_title_reason:
        return tmdb_title_reason
    for term in keyword_terms:
        if not _term_in_text(term, raw_haystack, compact_haystack):
            return f"关键词未命中:{term[0]}"
    quality_reason = _quality_rule_skip_reason(subscription, result, *extra_texts)
    if quality_reason:
        return quality_reason
    return _episode_skip_reason(subscription, result, *extra_texts)


def _tmdb_title_skip_reason(subscription: dict, text: str, title_term: tuple[str, str] | None) -> str:
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "").lstrip("0")
    text_tmdb_ids = _tmdb_ids_from_text(text)
    if subscription_tmdb_id and text_tmdb_ids:
        if subscription_tmdb_id not in text_tmdb_ids:
            return "TMDB ID 不匹配"
        return ""
    if not title_term or not _title_term_in_text(title_term, text):
        return "标题未命中"
    return ""


def _episode_skip_reason(subscription: dict, result: SearchResult, *extra_texts: str) -> str:
    if subscription.get("media_type") != "tv":
        return "电影已入库" if subscription.get("in_library") else "已匹配"
    if subscription.get("emby_snapshot_failed"):
        return "Emby 快照失败"
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return "已匹配"
    missing = _missing_episode_keys(subscription)
    if not missing:
        return "订阅已完整入库"
    episodes = _episode_keys_from_text_for_subscription(subscription, _result_text(result, *extra_texts))
    if not episodes:
        return "未识别到集数"
    if not (episodes & missing):
        return "集数不在缺集范围"
    return "已匹配"


def _skip_reason_summary(subscription: dict, results: list[SearchResult], *extra_texts: str) -> str:
    counter: Counter[str] = Counter()
    for result in results:
        try:
            counter[_result_skip_reason(subscription, result, *extra_texts)] += 1
        except Exception as exc:
            counter["原因统计失败"] += 1
            add_log(
                "warning",
                "subscription",
                "资源跳过原因统计异常，已忽略单条结果",
                {**_result_debug_payload(result), "error": str(exc)},
            )
    if not counter:
        return ""
    return "，".join(f"{reason} {count}" for reason, count in counter.most_common(4))
