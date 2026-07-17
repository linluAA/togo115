from __future__ import annotations

import re
from typing import Any

from app.services.link.downloads import _download_link_key, is_valid_download_link
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.match.matching import result_matches_subscription
from app.services.subscription.match.result_utils import result_text
from app.services.subscription.match.text_utils import compact_match_text, years_from_text

def _query_without_year(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"[\(（\[【]\s*(?:19|20)\d{2}\s*[\)）\]】]", " ", text)
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _display_source(source: str | None) -> str:
    value = str(source or "\u8ba2\u9605\u6e90").strip()
    if ":" in value:
        value = value.split(":", 1)[1] or value
    return value[:40]


def _resource_size(result: Any) -> str:
    text = "\n".join(str(part or "") for part in (_result_attr(result, "title"), _result_attr(result, "context"), _result_attr(result, "url")))
    match = re.search(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(TiB|GiB|MiB|TB|GB|MB|T|G|M)(?![A-Za-z])", text, re.I)
    if not match:
        return ""
    number = match.group(1)
    unit = match.group(2).upper()
    unit = {"GIB": "GB", "MIB": "MB", "TIB": "TB", "G": "GB", "M": "MB", "T": "TB"}.get(unit, unit)
    return f"{number} {unit}"


def _result_attr(result: Any, name: str) -> Any:
    if isinstance(result, dict):
        return result.get(name) or result.get("link") if name == "url" else result.get(name)
    return getattr(result, name, None)


def _detail_title(detail: dict[str, Any]) -> str:
    return str(detail.get("name") or detail.get("title") or "").strip()


def _detail_year(detail: dict[str, Any]) -> str:
    return str(detail.get("first_air_date") or detail.get("release_date") or "")[:4]


def _search_title(detail: dict[str, Any]) -> str:
    title = _detail_title(detail)
    year = _detail_year(detail)
    return f"{title} {year}".strip()


def _search_keywords(detail: dict[str, Any]) -> list[str]:
    title = _detail_title(detail)
    original = str(detail.get("original_name") or detail.get("original_title") or "").strip()
    return [item for item in dict.fromkeys([title, original]) if item]


def _subscription_from_detail(media_type: str, tmdb_id: int, detail: dict[str, Any]) -> dict[str, Any]:
    title = _detail_title(detail)
    year = _detail_year(detail)
    return {
        "id": 0,
        "title": title,
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "release_year": int(year) if year.isdigit() else None,
        "keywords": [title],
        "search_aliases": _search_keywords(detail),
        "quality_rules": {},
        "tmdb_total_count": detail.get("number_of_episodes") or 0,
        "tmdb_seasons": detail.get("seasons") or [],
        "emby_episode_keys": [],
        "emby_count": 0,
        "in_library": False,
    }


def _is_magnet_result(result: SearchResult) -> bool:
    url = str(getattr(result, "url", "") or "").strip()
    return url.casefold().startswith("magnet:?") and is_valid_download_link(url)


def _rank_magnet_results(subscription: dict[str, Any], results: list[SearchResult]) -> list[SearchResult]:
    seen: set[tuple[str, str]] = set()
    scored: list[tuple[int, int, int, SearchResult]] = []
    for index, result in enumerate(results):
        key = _download_link_key(result.url)
        if key in seen:
            continue
        seen.add(key)
        score = _result_score(subscription, result)
        if score <= 0:
            continue
        scored.append((score, int(getattr(result, "priority", 0) or 0), -index, result))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [item[3] for item in scored]


def _result_score(subscription: dict[str, Any], result: SearchResult) -> int:
    text = result_text(result)
    if not _bot_title_or_alias_matches(subscription, text):
        return 0
    year = subscription.get("release_year")
    years = years_from_text(text)
    if year and years and int(year) not in years:
        return 0
    try:
        if result_matches_subscription(subscription, result):
            return 100 + _quality_score(text)
    except Exception:
        pass
    return 60 + _quality_score(text)



def _bot_title_or_alias_matches(subscription: dict[str, Any], text: str) -> bool:
    raw_text = str(text or "")
    compact_text = compact_match_text(raw_text)
    candidates = [subscription.get("title"), *(subscription.get("search_aliases") or [])]
    for item in candidates:
        term = _query_without_year(str(item or "")).strip()
        compact = compact_match_text(term)
        if not compact:
            continue
        if _contains_cjk(term):
            if _cjk_title_match(term, raw_text):
                return True
            continue
        if _latin_title_match(compact, compact_text):
            return True
    return False


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))


def _cjk_title_match(term: str, text: str) -> bool:
    normalized_term = re.sub(r"\s+", "", term)
    normalized_text = re.sub(r"\s+", "", text or "")
    if not normalized_term:
        return False
    start = 0
    while True:
        index = normalized_text.find(normalized_term, start)
        if index < 0:
            return False
        before = normalized_text[index - 1] if index > 0 else ""
        after_index = index + len(normalized_term)
        after = normalized_text[after_index] if after_index < len(normalized_text) else ""
        if _cjk_prefix_boundary(before) and _cjk_suffix_boundary(after):
            return True
        start = index + 1


def _cjk_prefix_boundary(char: str) -> bool:
    return not char or not re.match(r"[\u3400-\u9fffA-Za-z0-9]", char)


def _cjk_suffix_boundary(char: str) -> bool:
    if not char:
        return True
    if char.isdigit():
        return True
    return bool(re.match(r"[\s\[\]\(\)【】（）._\-/·]", char))


def _latin_title_match(term: str, compact_text: str) -> bool:
    if not term:
        return False
    start = 0
    while True:
        index = compact_text.find(term, start)
        if index < 0:
            return False
        before = compact_text[index - 1] if index > 0 else ""
        after_index = index + len(term)
        after = compact_text[after_index] if after_index < len(compact_text) else ""
        before_is_word = before.isascii() and before.isalnum()
        after_is_word = after.isascii() and after.isalnum()
        if not before_is_word and not after_is_word:
            return True
        if index == 0 and (not after or after.isdigit()):
            return True
        start = index + 1


def _quality_score(text: str) -> int:
    value = text.casefold()
    score = 0
    for pattern, points in ((r"2160p|4k|uhd", 8), (r"1080p", 6), (r"web-?dl|webrip", 4), (r"bluray|blu-ray", 3), (r"h\.265|x265|hevc", 2)):
        if re.search(pattern, value):
            score += points
    return score


