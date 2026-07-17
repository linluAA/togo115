from __future__ import annotations

import re
from typing import Any

from app.services.magnet.constants import (
    TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS,
    TG_BOT_MAGNET_DETAIL_LIMIT,
    TG_BOT_MAGNET_SOURCE_QUERY_LIMIT,
    TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS,
)


def _fast_magnet_query_batches(title: str, keywords: list[str]) -> list[list[str]]:
    queries = _fast_magnet_queries(title, keywords)
    if not queries:
        return []
    first = queries[:1]
    second = queries[1:TG_BOT_MAGNET_SOURCE_QUERY_LIMIT + 1]
    return [batch for batch in (first, second) if batch]

def _fast_magnet_queries(title: str, keywords: list[str]) -> list[str]:
    queries: list[str] = []

    def add(value: str | None) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if normalized and normalized not in queries:
            queries.append(normalized)

    add(title)
    add(_query_without_year(title))
    for keyword in keywords:
        add(keyword)
        add(_query_without_year(keyword))
    return queries[:4]

def _query_without_year(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"[\(（\[【]\s*(?:19|20)\d{2}\s*[\)）\]】]", " ", text)
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _fast_source_options(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **source,
        "_fast_detail_limit": TG_BOT_MAGNET_DETAIL_LIMIT,
        "_bt1207_detail_delay": TG_BOT_MAGNET_BT1207_DETAIL_DELAY_SECONDS,
        "_parallel_details": True,
        "_request_timeout": min(TG_BOT_MAGNET_SOURCE_TIMEOUT_SECONDS, 8.0),
    }
