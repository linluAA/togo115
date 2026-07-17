from __future__ import annotations

import re
from typing import Any

from app.db import row_to_dict
from app.services.adapters.telegram.scan.message_titles import _telegram_resource_title
from app.services.link import (
    compact_search_text,
    context_for_115_link,
    local_text_matches_query,
)
from app.services.text_cjk import query_match_aliases
from app.services.types import SearchResult

TELEGRAM_INDEX_QUERY_LIMIT = 600
TELEGRAM_INDEX_PREFILTER_LIMIT = 120
TELEGRAM_INDEX_FTS_LIMIT = 160


def search_blob_for(text: str, context: str) -> str:
    raw = f"{context}\n{text}"
    # Compact + simplified form for SQL LIKE / FTS against subscription query stems.
    return compact_search_text(raw)


def index_prefilter_terms(queries: list[str]) -> list[str]:
    """Extract short stems used for SQL LIKE / FTS prefiltering.

    Uses both original and simplified/prefix-stripped aliases so traditional
    cards and simplified subscriptions can hit. Longer stems are preferred.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        text = str(value or "").strip()
        if len(text) < 2:
            return
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
            compact = compact_search_text(alias)
            if compact:
                add(compact)
            if len(terms) >= 12:
                break
        if len(terms) >= 12:
            break
    terms.sort(key=lambda item: (-len(item), item.casefold()))
    return terms


def candidate_rows(
    conn: Any,
    sources: list[str],
    prefilter_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    clean_sources = [str(source).strip() for source in sources if str(source).strip()]
    if not clean_sources:
        return []
    terms = [str(term).strip() for term in (prefilter_terms or []) if str(term).strip()]
    compact_terms: list[str] = []
    seen: set[str] = set()
    for term in terms:
        compact = compact_search_text(term)
        if compact and compact not in seen:
            seen.add(compact)
            compact_terms.append(compact)
    compact_terms.sort(key=lambda item: (-len(item), item))

    fts_rows = _candidate_rows_fts(conn, clean_sources, compact_terms)
    if fts_rows:
        _note_index_path("fts", len(fts_rows))
        return fts_rows

    like_rows = _candidate_rows_like(conn, clean_sources, compact_terms)
    if like_rows:
        _note_index_path("like", len(like_rows))
        return like_rows

    recent_rows = _candidate_rows_recent(conn, clean_sources)
    _note_index_path("recent", len(recent_rows))
    return recent_rows


def _note_index_path(path: str, count: int) -> None:
    try:
        from app.services.metrics import record_index_query

        record_index_query({"path": path, "count": int(count or 0)})
    except Exception:
        pass


def _candidate_rows_fts(conn: Any, sources: list[str], compact_terms: list[str]) -> list[dict[str, Any]]:
    if not compact_terms:
        return []
    match = _fts_match_query(compact_terms[:4])
    if not match:
        return []
    placeholders = ",".join("?" for _ in sources)
    sql = f"""
        SELECT i.source, i.message_id, i.text, i.context
        FROM telegram_message_index_fts
        JOIN telegram_message_index i
          ON i.source = telegram_message_index_fts.source
         AND i.message_id = telegram_message_index_fts.message_id
        WHERE i.has_115 = 1
          AND i.source IN ({placeholders})
          AND telegram_message_index_fts MATCH ?
        ORDER BY i.message_id DESC
        LIMIT ?
    """
    params: list[Any] = [*sources, match, TELEGRAM_INDEX_FTS_LIMIT]
    try:
        fetched = conn.execute(sql, params).fetchall()
    except Exception:
        return []
    return [row_to_dict(row) or {} for row in fetched]


def _candidate_rows_like(conn: Any, sources: list[str], compact_terms: list[str]) -> list[dict[str, Any]]:
    if not compact_terms:
        return []
    stems = compact_terms[:4]
    like_clauses = ["search_blob LIKE ?" for _ in stems]
    placeholders = ",".join("?" for _ in sources)
    sql = f"""
        SELECT source, message_id, text, context
        FROM telegram_message_index
        WHERE has_115 = 1
          AND source IN ({placeholders})
          AND ({" OR ".join(like_clauses)})
        ORDER BY message_id DESC
        LIMIT ?
    """
    params: list[Any] = [*sources, *[f"%{term}%" for term in stems], TELEGRAM_INDEX_PREFILTER_LIMIT]
    try:
        fetched = conn.execute(sql, params).fetchall()
    except Exception:
        return []
    return [row_to_dict(row) or {} for row in fetched]


def _candidate_rows_recent(conn: Any, sources: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in sources)
    sql = f"""
        SELECT source, message_id, text, context
        FROM telegram_message_index
        WHERE has_115 = 1
          AND source IN ({placeholders})
        ORDER BY message_id DESC
        LIMIT ?
    """
    limit = min(TELEGRAM_INDEX_QUERY_LIMIT, max(80, 40 * len(sources)))
    try:
        fetched = conn.execute(sql, [*sources, limit]).fetchall()
    except Exception:
        return []
    return [row_to_dict(row) or {} for row in fetched]


def _fts_match_query(terms: list[str]) -> str:
    """Build an FTS5 MATCH expression with CJK bi-gram expansion."""
    parts: list[str] = []
    for term in terms:
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(term or ""), flags=re.UNICODE).strip()
        if len(cleaned) < 2:
            continue
        token = cleaned.replace('"', " ").strip()
        if not token:
            continue
        parts.append(f'"{token}"')
        for gram in _cjk_ngrams(token, size=2):
            parts.append(f'"{gram}"')
        if len(parts) >= 12:
            break
    if not parts:
        return ""
    uniq = list(dict.fromkeys(parts))
    return " OR ".join(uniq[:12])


def _cjk_ngrams(text: str, *, size: int = 2) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or ""))
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]+", compact)
    grams: list[str] = []
    for chunk in cjk_chunks:
        if len(chunk) < size:
            continue
        for index in range(0, len(chunk) - size + 1):
            grams.append(chunk[index : index + size])
    return grams


def row_to_result(row: dict[str, Any], url: str, context: str, matched_query: str) -> SearchResult:
    message_id = str(row.get("message_id") or "")
    title = title_from_context(context, matched_query)
    safe_context = context
    if title and not str(title).startswith("Telegram ") and title not in context:
        safe_context = f"{title}\n{url}"
    elif title and not str(title).startswith("Telegram "):
        safe_context = context_for_115_link(context, url, 2) or context
    origin = str(row.get("source") or "").strip()
    source_label = f"TelegramIndex:{origin}" if origin else "TelegramIndex"
    return SearchResult(
        title=title,
        url=url,
        source=source_label,
        message_id=message_id,
        context=safe_context,
        priority=30,
    )


def title_from_context(context: str, matched_query: str) -> str:
    title = _telegram_resource_title(context)
    if title and not str(title).startswith("Telegram "):
        return title[:160]
    for line in context.splitlines():
        if matched_query and local_text_matches_query(line, matched_query):
            return line.strip()[:160]
    return matched_query or "Telegram index hit"
