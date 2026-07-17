from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import utc_now
from app.services.adapters.telegram.scan.message_index_query import search_blob_for
from app.services.link import (
    extract_115_links,
    message_has_link_button_hint,
    telegram_message_text,
    text_has_external_resource_page_hint,
)


def index_rows(source: str, messages: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    indexed_at = utc_now()
    for index, message in enumerate(messages):
        message_id = int(getattr(message, "id", 0) or 0)
        text = telegram_message_text(message)
        if not message_id or not text:
            continue
        context = message_context(messages, index)
        rows.append(
            {
                "source": source,
                "message_id": message_id,
                "text": text,
                "context": context,
                "search_blob": search_blob_for(text, context),
                "has_115": 1 if extract_115_links(text) else 0,
                "has_link_hint": 1 if has_link_hint(message, context) else 0,
                "message_date": message_date(message),
                "indexed_at": indexed_at,
            }
        )
    return rows


def message_context(messages: list[Any], index: int) -> str:
    """Build a tight card context for index rows.

    Index is an early-return cache, so it prefers precision over recall:
    - non-link messages stay as themselves
    - link messages may take only the immediately previous non-link message
    - never cross another 115 share
    """
    current = telegram_message_text(messages[index]).strip()
    if not current:
        return ""
    if not extract_115_links(current):
        return current
    if index <= 0:
        return current
    previous = telegram_message_text(messages[index - 1]).strip()
    if not previous or extract_115_links(previous):
        return current
    return f"{previous}\n{current}"


def has_link_hint(message: Any, context: str) -> bool:
    return bool(
        extract_115_links(context)
        or text_has_external_resource_page_hint(context)
        or message_has_link_button_hint(message)
    )


def message_date(message: Any) -> str | None:
    value = getattr(message, "date", None)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None
