from __future__ import annotations

import re

from app.services.link.telegram_context import _resource_title_line_score, context_for_115_link
from app.services.link.telegram_hints import (
    TELEGRAM_LINK_BUTTON_WORDS,
    _looks_like_context_message,
    _looks_like_link_only_message,
    _message_button_values,
    _message_has_link_button_hint,
    _nearby_link_text_matches,
    _nearby_recent_message_texts,
    _nearby_recent_messages_have_button_hint,
    _remove_115_links_for_hint,
    _text_has_external_resource_page_hint,
)
from app.services.link.telegram_message import (
    _add_text_part,
    _collect_dict_texts,
    _safe_attr,
    _text_part,
    telegram_message_text,
)


HTTP_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.I)

TELEGRAM_EXTERNAL_PAGE_HOSTS = {
    "caiyun.139.com",
    "ctfile.com",
    "docs.qq.com",
    "drive.uc.cn",
    "feijipan.com",
    "flowus.cn",
    "kdocs.cn",
    "lanzouj.com",
    "lanzoui.com",
    "lanzoux.com",
    "lanzn.com",
    "pan.baidu.com",
    "pan.quark.cn",
    "pan.xunlei.com",
    "share.weiyun.com",
    "www.aliyundrive.com",
    "www.123pan.com",
    "123pan.com",
    "telegra.ph",
}

TELEGRAM_HISTORY_TOTAL_BUDGET_SECONDS = 70.0
TELEGRAM_HISTORY_QUERY_BUDGET_SECONDS = 4.0
TELEGRAM_HISTORY_RECENT_BUDGET_SECONDS = 12.0
TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT = 300
TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT = 500
TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY = 12
TELEGRAM_HISTORY_MAX_RESULTS = 30
TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS = 5.0
TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS = 5.0
TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE = 3
TELEGRAM_EXTERNAL_PAGE_TIMEOUT_SECONDS = 8.0
TELEGRAM_EXTERNAL_PAGE_MAX_FETCHES = 3


__all__ = [name for name in globals() if not name.startswith("__")]
