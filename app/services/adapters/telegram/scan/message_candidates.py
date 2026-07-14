from __future__ import annotations

from typing import Any

from app.services.link_parser import (
    _looks_like_context_message,
    context_for_115_link,
    extract_115_links,
    telegram_message_text,
)


def telegram_candidate_link_contexts(messages: list[Any], extra_texts: list[str] | None = None) -> dict[str, str]:
    """Build per-message resource contexts instead of mixing every nearby card together."""
    ordered = _ordered_messages(messages)
    contexts: dict[str, str] = {}

    for message in ordered:
        text = telegram_message_text(message)
        if not extract_115_links(text):
            continue
        block = telegram_candidate_context_text(message, ordered, extra_texts)
        _merge_link_contexts(contexts, block)

    extra_block = "\n".join(text for text in extra_texts or [] if text)
    if extract_115_links(extra_block):
        anchor = messages[0] if messages else None
        block = telegram_candidate_context_text(anchor, ordered, extra_texts) if anchor else extra_block
        _merge_link_contexts(contexts, block)

    if contexts:
        return contexts

    fallback = _combined_text([telegram_message_text(item) for item in ordered], extra_texts)
    _merge_link_contexts(contexts, fallback)
    return contexts


def telegram_candidate_context_text(
    anchor: Any,
    messages: list[Any],
    extra_texts: list[str] | None = None,
) -> str:
    """Return the smallest useful text block for the resource represented by anchor."""
    if anchor is None:
        return _combined_text([], extra_texts)
    anchor_text = telegram_message_text(anchor)
    anchor_id = _message_id(anchor)
    anchor_group = str(getattr(anchor, "grouped_id", "") or "")
    anchor_has_link = bool(extract_115_links(anchor_text))
    previous_link_id = _previous_link_message_id(anchor, messages) if anchor_has_link else 0
    before: list[str] = []
    after: list[str] = []

    for message in _ordered_messages(messages):
        if message is anchor:
            continue
        text = telegram_message_text(message)
        if not text:
            continue
        same_group = bool(anchor_group and str(getattr(message, "grouped_id", "") or "") == anchor_group)
        distance = abs(_message_id(message) - anchor_id) if anchor_id and _message_id(message) else 99
        if not same_group and distance > 4:
            continue
        if previous_link_id and _message_id(message) <= previous_link_id:
            continue
        if extract_115_links(text) and not same_group:
            continue
        if not same_group and not _looks_like_context_message(text) and len(text) > 160:
            continue
        if _message_id(message) and anchor_id and _message_id(message) < anchor_id:
            before.append(text)
        elif same_group or not anchor_has_link:
            after.append(text)

    return _combined_text([*before[-3:], anchor_text, *after[:2]], extra_texts)


def _merge_link_contexts(contexts: dict[str, str], text: str) -> None:
    links = extract_115_links(text)
    for link in links:
        contexts.setdefault(link, context_for_115_link(text, link, len(links)))


def _ordered_messages(messages: list[Any]) -> list[Any]:
    seen: set[str] = set()
    items: list[Any] = []
    for message in messages:
        if not message:
            continue
        key = str(getattr(message, "id", None) or id(message))
        if key in seen:
            continue
        seen.add(key)
        items.append(message)
    return sorted(items, key=lambda item: (_message_id(item) or 0, id(item)))


def _combined_text(texts: list[str], extra_texts: list[str] | None = None) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for text in [*texts, *(extra_texts or [])]:
        value = str(text or "").strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    return "\n".join(parts)


def _previous_link_message_id(anchor: Any, messages: list[Any]) -> int:
    anchor_id = _message_id(anchor)
    anchor_group = str(getattr(anchor, "grouped_id", "") or "")
    previous = 0
    for message in _ordered_messages(messages):
        message_id = _message_id(message)
        if not message_id or message_id >= anchor_id:
            continue
        same_group = bool(anchor_group and str(getattr(message, "grouped_id", "") or "") == anchor_group)
        if not same_group and extract_115_links(telegram_message_text(message)):
            previous = message_id
    return previous


def _message_id(message: Any) -> int:
    try:
        return int(getattr(message, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0
