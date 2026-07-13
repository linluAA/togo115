from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link_downloads import PAN115_LOOSE_URL_RE, _normalize_download_text, extract_115_links
from app.services.link_search_utils import _compact_search_text, _local_text_matches_query
from app.services.link_telegram_message import _safe_attr, _text_part, telegram_message_text


TELEGRAM_LINK_BUTTON_WORDS = (
    "115",
    "链接",
    "查看",
    "打开",
    "瞅我",
    "点我",
    "点击",
    "资源",
    "获取",
    "下载",
    "提取",
    "取链",
    "网盘",
    "详情",
    "link",
)
TELEGRAM_EXTERNAL_HINT_HOSTS = {
    "telegra.ph",
    "115.com",
    "www.115.com",
}
HTTP_URL_HINT_RE = re.compile(r'https?://[^\s"\'<>]+', re.I)
CONTEXT_MESSAGE_RE = re.compile(
    r"(电视剧|电影|动漫|动画|综艺|短剧|番剧|剧集|名称|片名|标题|资源|"
    r"S\d{1,2}E\d{1,3}|E\d{1,3}|第\s*\d{1,3}\s*[集话話]|"
    r"(?:19|20)\d{2}|1080|2160|4K|WEB|BluRay)",
    re.I,
)


def _remove_115_links_for_hint(text: str) -> str:
    value = _normalize_download_text(text)
    value = PAN115_LOOSE_URL_RE.sub(" ", value)
    value = PAN115_URL_RE.sub(" ", value)
    value = re.sub(r"(?i)\b(password|pwd|pass|code)\s*[:=]\s*[A-Za-z0-9_-]{2,}", " ", value)
    value = re.sub(r"(链接|提取码|访问码|密码|网盘|115|:|：|/|\\|\?|=|&|-|_|\s)+", " ", value)
    return value.strip()


def _looks_like_link_only_message(text: str) -> bool:
    if not extract_115_links(text):
        return False
    remainder = _remove_115_links_for_hint(text)
    return len(_compact_search_text(remainder)) <= 12


def _nearby_link_text_matches(text: str, queries: list[str] | None) -> bool:
    if not extract_115_links(text):
        return False
    if _looks_like_link_only_message(text):
        return True
    return any(_local_text_matches_query(text, query) for query in queries or [])


def _message_button_values(message: Any) -> list[str]:
    values: list[str] = []
    for row in _safe_attr(message, "buttons") or []:
        for button in row:
            values.extend(_button_text_values(button))
    return values


def _button_text_values(button: Any) -> list[str]:
    values: list[str] = []
    for value in (_safe_attr(button, "text"), _safe_attr(button, "url")):
        text = _text_part(value)
        if text:
            values.append(text)
    raw_button = _safe_attr(button, "button")
    if raw_button is None:
        return values
    for value in (_safe_attr(raw_button, "url"), _safe_attr(raw_button, "data")):
        text = _text_part(value)
        if text:
            values.append(text)
    return values


def _message_has_link_button_hint(message: Any) -> bool:
    for value in _message_button_values(message):
        normalized = value.casefold()
        if extract_115_links(value) or any(word in normalized for word in TELEGRAM_LINK_BUTTON_WORDS):
            return True
    return False


def _text_has_external_resource_page_hint(text: str | None) -> bool:
    for raw_url in HTTP_URL_HINT_RE.findall(str(text or "")):
        host = urlparse(raw_url).netloc.casefold()
        if host in TELEGRAM_EXTERNAL_HINT_HOSTS:
            return True
    return False


def _looks_like_context_message(text: str | None) -> bool:
    value = str(text or "").strip()
    if not value or extract_115_links(value):
        return False
    compact = _compact_search_text(value)
    if len(compact) < 2:
        return False
    if CONTEXT_MESSAGE_RE.search(value):
        return True
    return len(compact) <= 80


def _nearby_recent_message_texts(messages: list[Any], index: int, queries: list[str] | None, window: int = 4) -> list[str]:
    base = messages[index] if 0 <= index < len(messages) else None
    if not base:
        return []
    grouped_id = getattr(base, "grouped_id", None)
    texts: list[str] = []
    seen: set[str] = set()
    for nearby_index in range(max(0, index - window), min(len(messages), index + window + 1)):
        if nearby_index == index:
            continue
        nearby = messages[nearby_index]
        text = telegram_message_text(nearby)
        if not text or text in seen:
            continue
        nearby_grouped_id = getattr(nearby, "grouped_id", None)
        same_group = bool(grouped_id and nearby_grouped_id and str(nearby_grouped_id) == str(grouped_id))
        if same_group or _nearby_link_text_matches(text, queries):
            seen.add(text)
            texts.append(text)
    return texts


def _nearby_recent_messages_have_button_hint(messages: list[Any], index: int, window: int = 4) -> bool:
    for nearby_index in range(max(0, index - window), min(len(messages), index + window + 1)):
        if nearby_index == index:
            continue
        text = telegram_message_text(messages[nearby_index])
        if _message_has_link_button_hint(messages[nearby_index]) or _text_has_external_resource_page_hint(text):
            return True
    return False
