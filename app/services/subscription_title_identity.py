from __future__ import annotations

import re

from app.services.subscription_text_utils import _compact_match_text


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
    compact_text = _compact_match_text(text)
    title_has_cjk = bool(CJK_RE.search(compact_title))
    start = 0
    while True:
        index = compact_text.find(compact_title, start)
        if index < 0:
            return False
        after_index = index + len(compact_title)
        after = compact_text[after_index] if after_index < len(compact_text) else ""
        if _is_title_prefix_boundary(compact_text, index, title_has_cjk) and _is_title_suffix_boundary(after, title_has_cjk):
            return True
        start = index + 1


def _title_fragment_in_text(term: tuple[str, str] | None, text: str) -> bool:
    if not term:
        return False
    if len(term[1]) < 3:
        return _title_term_in_text(term, text)
    return term[1] in _compact_match_text(text)
