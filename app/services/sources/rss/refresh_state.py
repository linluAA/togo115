from __future__ import annotations

import time
from typing import Any

from app.services import integration_state as _state


def get_setting(*args, **kwargs):
    return _state.get_setting(*args, **kwargs)


def save_setting(*args, **kwargs):
    return _state.save_setting(*args, **kwargs)


class RssTorznabRefreshStateMixin:
    def _due_sources(self) -> list[dict[str, Any]]:
        now = time.time()
        sources = []
        for source in self._sources():
            if now - _last_checked_at(source) >= _refresh_interval_seconds(source):
                sources.append(source)
        return sources

    def _persist_source_refresh_times(self, sources: list[dict[str, Any]], checked_at: float) -> None:
        config = get_setting("rss_sources", {"sources": []})
        configured = config.get("sources") or []
        checked_by_id = {self._source_identity(source): source.get("last_checked_at") for source in sources}
        for item in configured:
            identity = self._source_identity(item)
            if identity in checked_by_id:
                item["last_checked_at"] = checked_by_id[identity]
        builtin_last_checked = config.get("builtin_last_checked") if isinstance(config.get("builtin_last_checked"), dict) else {}
        builtin_ids = {self._source_identity(source) for source in self.BUILTIN_SOURCES}
        for identity, source_checked_at in checked_by_id.items():
            if identity in builtin_ids:
                builtin_last_checked[identity] = source_checked_at or checked_at
        save_setting("rss_sources", {**config, "sources": configured, "builtin_last_checked": builtin_last_checked})


def _last_checked_at(source: dict[str, Any]) -> float:
    try:
        return float(source.get("last_checked_at") or 0)
    except (TypeError, ValueError):
        return 0


def _refresh_interval_seconds(source: dict[str, Any]) -> int:
    try:
        interval_minutes = int(source.get("refresh_interval") or 30)
    except (TypeError, ValueError):
        interval_minutes = 30
    return max(interval_minutes, 5) * 60
