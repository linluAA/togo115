from __future__ import annotations

from typing import Any

# Process-local hit scores so later searches in this worker prefer productive dialogs.
_PROCESS_DIALOG_HIT_SCORES: dict[str, int] = {}


def dialog_source_key(dialog: dict[str, Any] | str | None) -> str:
    if isinstance(dialog, dict):
        return str(dialog.get("canonical") or dialog.get("source") or "").strip()
    return str(dialog or "").strip()


def note_dialog_hit(source: str, amount: int = 1) -> None:
    key = str(source or "").strip()
    if not key or amount <= 0:
        return
    _PROCESS_DIALOG_HIT_SCORES[key] = int(_PROCESS_DIALOG_HIT_SCORES.get(key, 0) or 0) + int(amount)


def dialog_hit_score(source: str, extra_scores: dict[str, int] | None = None) -> int:
    key = str(source or "").strip()
    if not key:
        return 0
    score = int(_PROCESS_DIALOG_HIT_SCORES.get(key, 0) or 0)
    if extra_scores:
        score += int(extra_scores.get(key, 0) or 0)
    return score


def rank_dialogs(
    dialogs: list[dict[str, Any]],
    *,
    preferred_sources: list[str] | None = None,
    hit_scores: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Rank dialogs: preferred sources first, then higher historical hit scores."""
    if not dialogs:
        return []
    preferred = {
        str(item).strip()
        for item in (preferred_sources or [])
        if str(item).strip()
    }
    extra = hit_scores or {}

    def sort_key(dialog: dict[str, Any]) -> tuple[int, int, str]:
        source = dialog_source_key(dialog)
        preferred_rank = 0 if source and source in preferred else 1
        score = dialog_hit_score(source, extra)
        return (preferred_rank, -score, source)

    return sorted(dialogs, key=sort_key)


def clear_process_dialog_hit_scores() -> None:
    """Test helper."""
    _PROCESS_DIALOG_HIT_SCORES.clear()
