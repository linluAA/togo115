from __future__ import annotations

import httpx

from app.db import add_log
from app.services.adapters.media import TmdbAdapter
from app.services.adapters.pan115 import Pan115Adapter
from app.services.adapters.telegram import TelegramClientAdapter
from app.services.integration_state import get_flow, get_setting, module_proxy, save_flow, save_setting
from app.services.link_parser import context_for_115_link, extract_download_links, telegram_message_text
from app.services.sources.rss_torznab import RssTorznabAdapter
from app.services.types import SearchResult

__all__ = [
    "Pan115Adapter",
    "RssTorznabAdapter",
    "SearchResult",
    "TelegramClientAdapter",
    "TmdbAdapter",
    "add_log",
    "context_for_115_link",
    "extract_download_links",
    "get_flow",
    "get_setting",
    "httpx",
    "module_proxy",
    "save_flow",
    "save_setting",
    "telegram_message_text",
]
