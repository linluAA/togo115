from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any

from app.db import db, row_to_dict, utc_now
from app.services.link_parser import (
    _local_text_matches_query,
    _message_has_link_button_hint,
    _text_has_external_resource_page_hint,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult

TELEGRAM_INDEX_WINDOW = 4
TELEGRAM_INDEX_MAX_PER_SOURCE = 2500
TELEGRAM_INDEX_QUERY_LIMIT = 600


def index_telegram_messages(source: str, messages: list[Any]) -> int:
    """Persist a small searchable index of Telegram message text and nearby context."""
    items = _index_rows(source, messages)
    if not items:
        return 0
    try:
        with db() as conn:
            conn.executemany(
                """
                INSERT INTO telegram_message_index
                    (source, message_id, text, context, has_115, has_link_hint, message_date, indexed_at)
                VALUES
                    (:source, :message_id, :text, :context, :has_115, :has_link_hint, :message_date, :indexed_at)
                ON CONFLICT(source, message_id) DO UPDATE SET
                    text = excluded.text,
                    context = excluded.context,
                    has_115 = excluded.has_115,
                    has_link_hint = excluded.has_link_hint,
                    message_date = excluded.message_date,
                    indexed_at = excluded.indexed_at
                """,
                items,
            )
            _prune_source_index(conn, source)
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return 0
        raise
    return len(items)


def search_telegram_message_index(sources: list[str], queries: list[str], limit: int) -> list[SearchResult]:
    if not sources or not queries or limit <= 0:
        return []
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    try:
        with db() as conn:
            for row in _candidate_rows(conn, sources):
                context = str(row.get("context") or row.get("text") or "")
                matched_query = next((query for query in queries if _local_text_matches_query(context, query)), "")
                if not matched_query:
                    continue
                for url in extract_115_links(context):
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    results.append(_row_to_result(row, url, context, matched_query))
                    if len(results) >= limit:
                        return results
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return []
        raise
    return results


def _index_rows(source: str, messages: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    indexed_at = utc_now()
    for index, message in enumerate(messages):
        message_id = int(getattr(message, "id", 0) or 0)
        text = telegram_message_text(message)
        if not message_id or not text:
            continue
        context = _message_context(messages, index)
        rows.append(
            {
                "source": source,
                "message_id": message_id,
                "text": text,
                "context": context,
                "has_115": 1 if extract_115_links(context) else 0,
                "has_link_hint": 1 if _has_link_hint(message, context) else 0,
                "message_date": _message_date(message),
                "indexed_at": indexed_at,
            }
        )
    return rows


def _message_context(messages: list[Any], index: int) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for item_index in range(max(0, index - TELEGRAM_INDEX_WINDOW), min(len(messages), index + TELEGRAM_INDEX_WINDOW + 1)):
        text = telegram_message_text(messages[item_index]).strip()
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    return "\n".join(parts)


def _has_link_hint(message: Any, context: str) -> bool:
    return bool(extract_115_links(context) or _text_has_external_resource_page_hint(context) or _message_has_link_button_hint(message))


def _message_date(message: Any) -> str | None:
    value = getattr(message, "date", None)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _candidate_rows(conn: Any, sources: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        fetched = conn.execute(
            """
            SELECT source, message_id, text, context
            FROM telegram_message_index
            WHERE source = ? AND has_115 = 1
            ORDER BY message_id DESC
            LIMIT ?
            """,
            (source, TELEGRAM_INDEX_QUERY_LIMIT),
        ).fetchall()
        rows.extend(row_to_dict(row) or {} for row in fetched)
    return rows


def _row_to_result(row: dict[str, Any], url: str, context: str, matched_query: str) -> SearchResult:
    message_id = str(row.get("message_id") or "")
    title = _title_from_context(context, matched_query)
    return SearchResult(title=title, url=url, source="TelegramIndex", message_id=message_id, context=context, priority=30)


def _title_from_context(context: str, matched_query: str) -> str:
    for line in context.splitlines():
        if matched_query and _local_text_matches_query(line, matched_query):
            return line.strip()[:160]
    return matched_query or "Telegram 索引命中"


def _prune_source_index(conn: Any, source: str) -> None:
    conn.execute(
        """
        DELETE FROM telegram_message_index
        WHERE source = ?
          AND message_id NOT IN (
              SELECT message_id
              FROM telegram_message_index
              WHERE source = ?
              ORDER BY message_id DESC
              LIMIT ?
          )
        """,
        (source, source, TELEGRAM_INDEX_MAX_PER_SOURCE),
    )


def _index_table_missing(exc: sqlite3.OperationalError) -> bool:
    return "telegram_message_index" in str(exc) and "no such table" in str(exc).casefold()
