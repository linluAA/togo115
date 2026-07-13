from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    source: str
    message_id: str | None = None
    context: str = ""
    priority: int = 0
