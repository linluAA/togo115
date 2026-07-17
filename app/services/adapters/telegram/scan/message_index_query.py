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


def search_blob_for(text: str, context: str) -> str:
    raw = f"{context}\n{text}"
    # Compact + simplified form for SQL LIKE against subscription query stems.
    return compact_search_text(raw)


def index_prefilter_terms(queries: list[str]) -> list[str]:
    """Extract short stems used for SQL LIKE prefiltering.

    Uses both original and simplified/prefix-stripped aliases so traditional
    cards and simplified subscriptions can hit.
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
            compact = compact_search_text(alias)
            if compact:
                add(compact)
            if len(terms) >= 12:
                return terms
    return terms


def candidate_rows(
    conn: Any,
    sources: list[str],
    prefilter_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    terms = [str(term).strip() for term in (prefilter_terms or []) if str(term).strip()]
    # Prefer compact/simplified stems for search_blob matching.
    compact_terms = []
    seen = set()
    for term in terms:
        compact = compact_search_text(term)
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


def row_to_result(row: dict[str, Any], url: str, context: str, matched_query: str) -> SearchResult:
    message_id = str(row.get("message_id") or "")
    title = title_from_context(context, matched_query)
    # Keep context limited to the accepted title segment so subscription match cannot re-expand
    # into neighboring cards that only appeared in the raw window.
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
    return matched_query or "Telegram 索引命中"
