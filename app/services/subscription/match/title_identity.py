from __future__ import annotations

import re

from app.services.subscription.match.text_utils import compact_match_text
from app.services.text_cjk import title_prefix_aliases


CJK_RE = re.compile(r"[\u3400-\u9fff]")
TITLE_PREFIX_LABELS = (
    "名称",
    "片名",
    "剧名",
    "标题",
    "资源",
    "资源名",
    "电视剧",
    "电影",
    "动漫",
    "动画",
    "综艺",
    "剧集",
    "短剧",
    "番剧",
    "name",
    "title",
)
TITLE_SUFFIX_BOUNDARY_CHARS = set("第更连完终至季集话話期部篇上下中")


def _is_title_prefix_boundary(compact_text: str, index: int, title_has_cjk: bool) -> bool:
    if index <= 0:
        return True
    before = compact_text[index - 1]
    if not title_has_cjk:
        return not before.isalpha()
    if not CJK_RE.match(before):
        return True
    prefix = compact_text[max(0, index - 8):index]
    return any(prefix.endswith(label) for label in TITLE_PREFIX_LABELS)


def _is_title_suffix_boundary(char: str, title_has_cjk: bool) -> bool:
    if not char:
        return True
    if char.isdigit():
        return True
    if title_has_cjk:
        return char in TITLE_SUFFIX_BOUNDARY_CHARS or not CJK_RE.match(char)
    return not char.isalpha()


def _title_term_in_text(term: tuple[str, str], text: str) -> bool:
    compact_title = term[1]
    if not compact_title:
        return False
    compact_text = compact_match_text(text)
    candidates = [compact_title]
    # Also accept franchise packs that omit 新/续 prefixes present on the subscription title.
    raw_title = term[0]
    for alias in title_prefix_aliases(raw_title)[1:]:
        compact_alias = compact_match_text(alias)
        if compact_alias and compact_alias not in candidates:
            candidates.append(compact_alias)
    title_has_cjk = bool(CJK_RE.search(compact_title))
    for candidate in candidates:
        start = 0
        while True:
            index = compact_text.find(candidate, start)
            if index < 0:
                break
            after_index = index + len(candidate)
            after = compact_text[after_index] if after_index < len(compact_text) else ""
            if _is_title_prefix_boundary(compact_text, index, title_has_cjk) and _is_title_suffix_boundary(after, title_has_cjk):
                return True
            start = index + 1
    return False


def _title_fragment_in_text(term: tuple[str, str] | None, text: str) -> bool:
    if not term:
        return False
    compact_text = compact_match_text(text)
    candidates = [term[1]] if term[1] else []
    for alias in title_prefix_aliases(term[0])[1:]:
        compact_alias = compact_match_text(alias)
        if compact_alias and compact_alias not in candidates:
            candidates.append(compact_alias)
    for candidate in candidates:
        if not candidate:
            continue
        if len(candidate) < 3:
            if _title_term_in_text((term[0], candidate), text):
                return True
            continue
        if candidate in compact_text:
            return True
    return False
