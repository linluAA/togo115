from __future__ import annotations

"""Link parsing utilities — public package surface.

Prefer public names. Private ``_`` helpers remain available from submodules
(``app.services.link.downloads`` / ``html`` / ``telegram`` / ``search_utils``)
or via lazy ``__getattr__`` for transitional callers.
"""

from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link.downloads import (
    extract_115_links,
    extract_download_links,
    is_115_share_link,
    is_valid_download_link,
    _clean_download_link,
    _download_link_key,
)
from app.services.link.feed import _first_text, _item_context, _item_links
from app.services.link.html import (
    HTML_ANCHOR_RE,
    HTML_HREF_RE,
    _html_container_fragment,
    _html_hrefs,
    _html_page_title,
    _link_context_from_html,
    _strip_html,
    _title_from_link_context,
)
from app.services.link.search_utils import (
    _bounded_float,
    _bounded_int,
    _compact_search_text,
    _expanded_search_queries,
    _local_text_matches_query,
    _split_filter_words,
    _truthy,
    years_from_text,
)
from app.services.link.telegram import (
    HTTP_URL_RE,
    TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE,
    TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS,
    TELEGRAM_EXTERNAL_PAGE_HOSTS,
    TELEGRAM_EXTERNAL_PAGE_MAX_FETCHES,
    TELEGRAM_EXTERNAL_PAGE_TIMEOUT_SECONDS,
    TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT,
    TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY,
    TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT,
    TELEGRAM_HISTORY_MAX_RESULTS,
    TELEGRAM_HISTORY_QUERY_BUDGET_SECONDS,
    TELEGRAM_HISTORY_RECENT_BUDGET_SECONDS,
    TELEGRAM_HISTORY_TOTAL_BUDGET_SECONDS,
    TELEGRAM_LINK_BUTTON_WORDS,
    TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS,
    _looks_like_context_message,
    _looks_like_link_only_message,
    _message_button_values,
    _message_has_link_button_hint,
    _nearby_link_text_matches,
    _nearby_recent_messages_have_button_hint,
    _text_has_external_resource_page_hint,
    context_for_115_link,
    telegram_message_text,
)

# Public constants used by RSS site adapters
MAGNET_WEB_DETAIL_LIMIT = 8
BT1207_DETAIL_DELAY_SECONDS = 0.6
BT1207_DETAIL_RETRIES = 3

# Public aliases (preferred over underscore names)
download_link_key = _download_link_key
clean_download_link = _clean_download_link
expanded_search_queries = _expanded_search_queries
split_filter_words = _split_filter_words
compact_search_text = _compact_search_text
local_text_matches_query = _local_text_matches_query
truthy = _truthy
bounded_float = _bounded_float
bounded_int = _bounded_int
first_text = _first_text
item_context = _item_context
item_links = _item_links
html_page_title = _html_page_title
html_hrefs = _html_hrefs
html_container_fragment = _html_container_fragment
strip_html = _strip_html
link_context_from_html = _link_context_from_html
title_from_link_context = _title_from_link_context
looks_like_context_message = _looks_like_context_message
looks_like_link_only_message = _looks_like_link_only_message
message_button_values = _message_button_values
message_has_link_button_hint = _message_has_link_button_hint
nearby_link_text_matches = _nearby_link_text_matches
nearby_recent_messages_have_button_hint = _nearby_recent_messages_have_button_hint
text_has_external_resource_page_hint = _text_has_external_resource_page_hint

__all__ = [
    "PAN115_URL_RE",
    "HTTP_URL_RE",
    "HTML_ANCHOR_RE",
    "HTML_HREF_RE",
    "extract_115_links",
    "extract_download_links",
    "is_115_share_link",
    "is_valid_download_link",
    "years_from_text",
    "context_for_115_link",
    "telegram_message_text",
    "download_link_key",
    "clean_download_link",
    "expanded_search_queries",
    "split_filter_words",
    "compact_search_text",
    "local_text_matches_query",
    "truthy",
    "bounded_float",
    "bounded_int",
    "first_text",
    "item_context",
    "item_links",
    "html_page_title",
    "html_hrefs",
    "html_container_fragment",
    "strip_html",
    "link_context_from_html",
    "title_from_link_context",
    "looks_like_context_message",
    "looks_like_link_only_message",
    "message_button_values",
    "message_has_link_button_hint",
    "nearby_link_text_matches",
    "nearby_recent_messages_have_button_hint",
    "text_has_external_resource_page_hint",
    "TELEGRAM_HISTORY_MAX_RESULTS",
    "TELEGRAM_HISTORY_DEFAULT_FALLBACK_LIMIT",
    "TELEGRAM_HISTORY_DEFAULT_MESSAGES_PER_QUERY",
    "TELEGRAM_HISTORY_MAX_FALLBACK_LIMIT",
    "TELEGRAM_HISTORY_QUERY_BUDGET_SECONDS",
    "TELEGRAM_HISTORY_RECENT_BUDGET_SECONDS",
    "TELEGRAM_HISTORY_TOTAL_BUDGET_SECONDS",
    "TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE",
    "TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS",
    "TELEGRAM_EXTERNAL_PAGE_HOSTS",
    "TELEGRAM_EXTERNAL_PAGE_MAX_FETCHES",
    "TELEGRAM_EXTERNAL_PAGE_TIMEOUT_SECONDS",
    "TELEGRAM_LINK_BUTTON_WORDS",
    "TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS",
    "MAGNET_WEB_DETAIL_LIMIT",
    "BT1207_DETAIL_DELAY_SECONDS",
    "BT1207_DETAIL_RETRIES",
]


_PRIVATE_ALIASES = {
    "_download_link_key": download_link_key,
    "_clean_download_link": clean_download_link,
    "_expanded_search_queries": expanded_search_queries,
    "_split_filter_words": split_filter_words,
    "_compact_search_text": compact_search_text,
    "_local_text_matches_query": local_text_matches_query,
    "_truthy": truthy,
    "_bounded_float": bounded_float,
    "_bounded_int": bounded_int,
    "_first_text": first_text,
    "_item_context": item_context,
    "_item_links": item_links,
    "_html_page_title": html_page_title,
    "_html_hrefs": html_hrefs,
    "_html_container_fragment": html_container_fragment,
    "_strip_html": strip_html,
    "_link_context_from_html": link_context_from_html,
    "_title_from_link_context": title_from_link_context,
    "_looks_like_context_message": looks_like_context_message,
    "_looks_like_link_only_message": looks_like_link_only_message,
    "_message_button_values": message_button_values,
    "_message_has_link_button_hint": message_has_link_button_hint,
    "_nearby_link_text_matches": nearby_link_text_matches,
    "_nearby_recent_messages_have_button_hint": nearby_recent_messages_have_button_hint,
    "_text_has_external_resource_page_hint": text_has_external_resource_page_hint,
}


def __getattr__(name: str):
    if name in _PRIVATE_ALIASES:
        return _PRIVATE_ALIASES[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
