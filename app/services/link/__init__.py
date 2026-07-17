from __future__ import annotations

from app.services.adapters.pan115 import PAN115_URL_RE
from app.services.link.downloads import (
    BTIH_HASH_RE,
    DOWNLOAD_TEXT_TRANSLATION,
    INVISIBLE_URL_CHARS_RE,
    MAGNET_URL_RE,
    PAN115_LOOSE_URL_RE,
    PAN115_RECEIVE_CODE_RE,
    TORRENT_URL_RE,
    _append_115_receive_code,
    _clean_download_link,
    _download_link_key,
    _loose_115_link,
    _normalize_download_text,
    extract_115_links,
    extract_download_links,
)
from app.services.link.feed import _all_text, _first_text, _item_context, _item_links
from app.services.link.html import (
    HTML_ANCHOR_RE,
    HTML_CONTEXT_TAGS,
    HTML_HREF_RE,
    HTML_TITLE_RE,
    _html_container_fragment,
    _html_container_fragments,
    _html_hrefs,
    _html_page_title,
    _link_context_from_html,
    _strip_html,
    _title_from_link_context,
)
from app.services.link.search_utils import (
    LOCAL_SEARCH_DROP_RE,
    YEAR_RE,
    _bounded_float,
    _bounded_int,
    _compact_search_text,
    _expanded_search_queries,
    _local_text_matches_query,
    _query_without_year,
    _search_title_variants,
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
    _add_text_part,
    _collect_dict_texts,
    _looks_like_context_message,
    _looks_like_link_only_message,
    _message_button_values,
    _message_has_link_button_hint,
    _nearby_link_text_matches,
    _nearby_recent_message_texts,
    _nearby_recent_messages_have_button_hint,
    _remove_115_links_for_hint,
    _resource_title_line_score,
    _safe_attr,
    _text_has_external_resource_page_hint,
    _text_part,
    context_for_115_link,
    telegram_message_text,
)


MAGNET_WEB_DETAIL_LIMIT = 8
BT1207_DETAIL_DELAY_SECONDS = 0.6
BT1207_DETAIL_RETRIES = 3


__all__ = [name for name in globals() if not name.startswith("__")]
