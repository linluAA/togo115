from __future__ import annotations

import sqlite3
from typing import Any

from app.db import db
from app.services.adapters.telegram.scan.index_cache import (
    _NEGATIVE_INDEX_CACHE,
    _negative_cache_hit,
    _negative_cache_key,
    _negative_cache_store,
)
from app.services.adapters.telegram.scan.message_index_build import index_rows
from app.services.adapters.telegram.scan.message_index_query import (
    TELEGRAM_INDEX_QUERY_LIMIT,
    candidate_rows,
    index_prefilter_terms,
    row_to_result,
    search_blob_for,
)
from app.services.link import (
    context_for_115_link,
    extract_115_links,
    local_text_matches_query,
)
from app.services.types import SearchResult

TELEGRAM_INDEX_WINDOW = 4
TELEGRAM_INDEX_MAX_PER_SOURCE = 2500
TELEGRAM_INDEX_MAX_AGE_DAYS = 21

# Compatibility aliases used by tests/patches.
_search_blob_for = search_blob_for
_index_prefilter_terms = index_prefilter_terms
_candidate_rows = candidate_rows
_row_to_result = row_to_result


def index_telegram_messages(source: str, messages: list[Any]) -> int:
    """Persist a small searchable index of Telegram message text and nearby context."""
    items = index_rows(source, messages)
    if not items:
        return 0
    try:
        with db() as conn:
            conn.executemany(
                """
                INSERT INTO telegram_message_index
                    (source, message_id, text, context, search_blob, has_115, has_link_hint, message_date, indexed_at)
                VALUES
                    (:source, :message_id, :text, :context, :search_blob, :has_115, :has_link_hint, :message_date, :indexed_at)
                ON CONFLICT(source, message_id) DO UPDATE SET
                    text = excluded.text,
                    context = excluded.context,
                    search_blob = excluded.search_blob,
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


def max_indexed_message_id(source: str) -> int:
    """Highest message_id already indexed for a Telegram source, or 0."""
    key = str(source or "").strip()
    if not key:
        return 0
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT MAX(message_id) AS max_id FROM telegram_message_index WHERE source = ?",
                (key,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return 0
        raise
    if not row:
        return 0
    try:
        return int(row["max_id"] if isinstance(row, sqlite3.Row) else row[0] or 0)
    except Exception:
        try:
            return int(dict(row).get("max_id") or 0)
        except Exception:
            return 0


def search_telegram_message_index(sources: list[str], queries: list[str], limit: int) -> list[SearchResult]:
    if not sources or not queries or limit <= 0:
        return []
    if _negative_cache_hit(sources, queries):
        return []
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    prefilter_terms = index_prefilter_terms(queries)
    try:
        with db() as conn:
            for row in candidate_rows(conn, sources, prefilter_terms):
                text = str(row.get("text") or "")
                context = str(row.get("context") or text)
                links = extract_115_links(text)
                if not links:
                    continue
                matched_query = next((query for query in queries if local_text_matches_query(context, query)), "")
                if not matched_query:
                    continue
                for url in links:
                    if url in seen_urls:
                        continue
                    scoped = context_for_115_link(context, url, max(len(links), 2))
                    if not local_text_matches_query(scoped, matched_query):
                        continue
                    from app.services.adapters.telegram.scan.message_titles import _telegram_resource_title

                    title = _telegram_resource_title(scoped)
                    if title and not str(title).startswith("Telegram ") and not local_text_matches_query(title, matched_query):
                        continue
                    seen_urls.add(url)
                    results.append(row_to_result(row, url, scoped, matched_query))
                    if len(results) >= limit:
                        return results
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return []
        raise
    if not results:
        _negative_cache_store(sources, queries)
    return results


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
    # Drop stale rows even if under the per-source cap so FTS stays lean.
    conn.execute(
        """
        DELETE FROM telegram_message_index
        WHERE source = ?
          AND indexed_at IS NOT NULL
          AND indexed_at < datetime('now', ?)
        """,
        (source, f"-{int(TELEGRAM_INDEX_MAX_AGE_DAYS)} days"),
    )


def prune_old_index_rows(*, max_age_days: int | None = None) -> int:
    """Global age-based prune for telegram_message_index. Returns deleted row count."""
    days = int(TELEGRAM_INDEX_MAX_AGE_DAYS if max_age_days is None else max_age_days)
    if days <= 0:
        return 0
    try:
        with db() as conn:
            cur = conn.execute(
                """
                DELETE FROM telegram_message_index
                WHERE indexed_at IS NOT NULL
                  AND indexed_at < datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            return int(getattr(cur, "rowcount", 0) or 0)
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return 0
        raise


def _index_table_missing(exc: sqlite3.OperationalError) -> bool:
    return "telegram_message_index" in str(exc) and "no such table" in str(exc).casefold()
