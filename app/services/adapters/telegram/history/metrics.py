from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TelegramSearchMetrics:
    """Stage timings and counters for one Telegram search invocation."""

    resolve_ms: int = 0
    search_ms: int = 0
    extract_ms: int = 0
    index_hits: int = 0
    remote_hits: int = 0
    cancelled: int = 0
    dialogs: int = 0
    force_remote: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "resolve_ms": self.resolve_ms,
            "search_ms": self.search_ms,
            "extract_ms": self.extract_ms,
            "index_hits": self.index_hits,
            "remote_hits": self.remote_hits,
            "cancelled": self.cancelled,
            "dialogs": self.dialogs,
            "force_remote": self.force_remote,
            **self.extra,
        }
