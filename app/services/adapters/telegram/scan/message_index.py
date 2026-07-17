from __future__ import annotations

from datetime import datetime
import re
import sqlite3
from typing import Any

from app.db import db, row_to_dict, utc_now
from app.services.adapters.telegram.scan.message_titles import _telegram_resource_title
from app.services.link.search_utils import _compact_search_text, years_from_text
from app.services.text_cjk import query_match_aliases
from app.services.link import (
    _local_text_matches_query,
    _message_has_link_button_hint,
    _text_has_external_resource_page_hint,
    context_for_115_link,
    extract_115_links,
    telegram_message_text,
)
from app.services.types import SearchResult

TELEGRAM_INDEX_WINDOW = 4
TELEGRAM_INDEX_MAX_PER_SOURCE = 2500
TELEGRAM_INDEX_QUERY_LIMIT = 600
TELEGRAM_INDEX_NEGATIVE_TTL_SECONDS = 120.0
_NEGATIVE_INDEX_CACHE: dict[str, float] = {}


def _negative_cache_key(sources: list[str], queries: list[str]) -> str:
    source_key = ",".join(sorted(str(item) for item in sources))
    query_key = "|".join(str(item) for item in queries)
    return source_key + "::" + query_key


def _negative_cache_hit(sources: list[str], queries: list[str]) -> bool:
    import time as _time
    key = _negative_cache_key(sources, queries)
    expires = _NEGATIVE_INDEX_CACHE.get(key)
    if expires is None:
        return False
    if expires <= _time.monotonic():
        _NEGATIVE_INDEX_CACHE.pop(key, None)
        return False
    return True


def _negative_cache_store(sources: list[str], queries: list[str]) -> None:
    import time as _time
    key = _negative_cache_key(sources, queries)
    _NEGATIVE_INDEX_CACHE[key] = _time.monotonic() + TELEGRAM_INDEX_NEGATIVE_TTL_SECONDS
    if len(_NEGATIVE_INDEX_CACHE) > 512:
        now = _time.monotonic()
        expired = [item for item, exp in _NEGATIVE_INDEX_CACHE.items() if exp <= now]
        for item in expired:
            _NEGATIVE_INDEX_CACHE.pop(item, None)
        if len(_NEGATIVE_INDEX_CACHE) > 512:
            oldest = sorted(_NEGATIVE_INDEX_CACHE.items(), key=lambda pair: pair[1])[:128]
            for item, _ in oldest:
                _NEGATIVE_INDEX_CACHE.pop(item, None)


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
    prefilter_terms = _index_prefilter_terms(queries)
    try:
        with db() as conn:
            for row in _candidate_rows(conn, sources, prefilter_terms):
                text = str(row.get("text") or "")
                context = str(row.get("context") or text)
                links = extract_115_links(text)
                if not links:
                    continue
                matched_query = next((query for query in queries if _local_text_matches_query(context, query)), "")
                if not matched_query:
                    continue
                for url in links:
                    if url in seen_urls:
                        continue
                    scoped = context_for_115_link(context, url, max(len(links), 2))
                    if not _local_text_matches_query(scoped, matched_query):
                        continue
                    title = _telegram_resource_title(scoped)
                    if title and not str(title).startswith("Telegram ") and not _local_text_matches_query(title, matched_query):
                        continue
                    seen_urls.add(url)
                    results.append(_row_to_result(row, url, scoped, matched_query))
                    if len(results) >= limit:
                        return results
    except sqlite3.OperationalError as exc:
        if _index_table_missing(exc):
            return []
        raise
    if not results:
        _negative_cache_store(sources, queries)
    return results


def _search_blob_for(text: str, context: str) -> str:
    raw = f"{context}\n{text}"
    # Compact + simplified form for SQL LIKE against subscription query stems.
    return _compact_search_text(raw)


def _index_prefilter_terms(queries: list[str]) -> list[str]:
    """Extract short stems used for SQL LIKE prefiltering.

    Uses both original and simplified/prefix-stripped aliases so traditional
    cards (攻殻機動隊) and simplified subscriptions (新攻壳机动队) can hit.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        text = str(value or "").strip()
        if len(text) < 2:
            return
        # Strip years and whitespace for broader LIKE stems.
        text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
        text = re.sub(r"\s+", "", text)
        if len(text) < 2:
            return
        if len(text) > 24:
            text = text[:24]
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        terms.append(text)

    for query in queries:
        for alias in query_match_aliases(query) or [str(query or "").strip()]:
            add(alias)
            # Also keep a compact simplified form for punctuation-free rows.
            compact = _compact_search_text(alias)
            if compact:
                add(compact)
            if len(terms) >= 12:
                return terms
    return terms


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
                "search_blob": _search_blob_for(text, context),
                "has_115": 1 if extract_115_links(text) else 0,
                "has_link_hint": 1 if _has_link_hint(message, context) else 0,
                "message_date": _message_date(message),
                "indexed_at": indexed_at,
            }
        )
    return rows


def _message_context(messages: list[Any], index: int) -> str:
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




def _has_link_hint(message: Any, context: str) -> bool:
    return bool(extract_115_links(context) or _text_has_external_resource_page_hint(context) or _message_has_link_button_hint(message))


def _message_date(message: Any) -> str | None:
    value = getattr(message, "date", None)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _candidate_rows(conn: Any, sources: list[str], prefilter_terms: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    terms = [str(term).strip() for term in (prefilter_terms or []) if str(term).strip()]
    # Prefer compact/simplified stems for search_blob matching.
    compact_terms = []
    seen = set()
    for term in terms:
        compact = _compact_search_text(term)
        if compact and compact not in seen:
            seen.add(compact)
            compact_terms.append(compact)
    for source in sources:
        fetched = []
        if compact_terms:
            like_clauses = []
            params: list[Any] = [source]
            for term in compact_terms:
                like_clauses.append("search_blob LIKE ?")
                params.append(f"%{term}%")
            where_like = " OR ".join(like_clauses)
            sql = f"""
                SELECT source, message_id, text, context
                FROM telegram_message_index
                WHERE source = ? AND has_115 = 1 AND ({where_like})
                ORDER BY message_id DESC
                LIMIT ?
            """
            params.append(min(TELEGRAM_INDEX_QUERY_LIMIT, 200))
            try:
                fetched = conn.execute(sql, params).fetchall()
            except Exception:
                fetched = []
        if not fetched:
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
    # Keep context limited to the accepted title segment so subscription match cannot re-expand
    # into neighboring cards that only appeared in the raw window.
    safe_context = context
    if title and not str(title).startswith("Telegram ") and title not in context:
        safe_context = f"{title}\n{url}"
    elif title and not str(title).startswith("Telegram "):
        safe_context = context_for_115_link(context, url, 2) or context
    origin = str(row.get("source") or "").strip()
    source_label = f"TelegramIndex:{origin}" if origin else "TelegramIndex"
    return SearchResult(title=title, url=url, source=source_label, message_id=message_id, context=safe_context, priority=30)


def _title_from_context(context: str, matched_query: str) -> str:
    title = _telegram_resource_title(context)
    if title and not str(title).startswith("Telegram "):
        return title[:160]
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
