from __future__ import annotations

from app.services.subscription_episode_parser import (
    FULL_SERIES_PACK_RE,
    SEASON_PACK_WORD_RE,
    STRONG_PACK_WORD_RE,
    _episode_counts_from_pack_text,
    episodes_from_text,
)
from app.services.subscription_result_utils import _result_text
from app.services.subscription_text_utils import (
    _compact_match_text,
    _normalize_quality_rules,
)
from app.services.types import SearchResult


def _text_contains_any(text: str, words: list[str]) -> bool:
    raw = text.casefold()
    compact = _compact_match_text(text)
    return any(word.casefold() in raw or _compact_match_text(word) in compact for word in words if word)


def _is_pack_result_text(text: str) -> bool:
    episodes = episodes_from_text(text)
    if len(episodes) > 1 or _episode_counts_from_pack_text(text):
        return True
    if SEASON_PACK_WORD_RE.search(text or "") or FULL_SERIES_PACK_RE.search(text or ""):
        return not episodes or bool(STRONG_PACK_WORD_RE.search(text or ""))
    return False


def _quality_rule_skip_reason(subscription: dict, result: SearchResult, *extra_texts: str) -> str:
    rules = _normalize_quality_rules(subscription.get("quality_rules"))
    text = _result_text(result, *extra_texts)
    exclude_words = rules.get("exclude_keywords") or []
    if exclude_words and _text_contains_any(text, exclude_words):
        return "命中排除词"
    release_groups = rules.get("release_groups") or []
    if release_groups and not _text_contains_any(text, release_groups):
        return "压制组未命中"
    accept_mode = rules.get("accept_mode") or "all"
    if accept_mode != "all":
        is_pack = _is_pack_result_text(text)
        if accept_mode == "pack" and not is_pack:
            return "仅接受合集"
        if accept_mode == "single" and is_pack:
            return "仅接受单集"
    return ""


def result_matches_quality_rules(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    return not _quality_rule_skip_reason(subscription, result, *extra_texts)


