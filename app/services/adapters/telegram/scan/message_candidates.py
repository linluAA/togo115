from __future__ import annotations

from typing import Any

from app.services.link import (
    _looks_like_context_message,
    _looks_like_link_only_message,
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
        # When callers already pass nearby title text (recent title/link windows),
        # prefer a title-first block so query filtering does not drop link-only shares.
        title_first = _title_first_context_block(contexts, extra_texts)
        if title_first:
            return title_first
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

    title_extras, other_extras = _split_title_extras(extra_texts)
    return _combined_text([*title_extras, *before[-3:], anchor_text, *after[:2], *other_extras], None)


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


def _split_title_extras(extra_texts: list[str] | None) -> tuple[list[str], list[str]]:
    titles: list[str] = []
    others: list[str] = []
    for text in extra_texts or []:
        value = str(text or "").strip()
        if not value:
            continue
        if extract_115_links(value) and _looks_like_link_only_message(value):
            others.append(value)
            continue
        if _looks_like_context_message(value) or not extract_115_links(value):
            titles.append(value)
        else:
            others.append(value)
    return titles, others


def _title_first_context_block(contexts: dict[str, str], extra_texts: list[str] | None) -> dict[str, str] | None:
    title_extras, _other = _split_title_extras(extra_texts)
    if not title_extras or not contexts:
        return None
    improved: dict[str, str] = {}
    for link, context in contexts.items():
        if any(_title_blob_in_context(context, title) for title in title_extras):
            improved[link] = context
            continue
        combined = _combined_text([*title_extras, context], None)
        improved[link] = context_for_115_link(combined, link, max(len(contexts), 1)) or combined
    return improved


def _title_blob_in_context(context: str, title: str) -> bool:
    compact_title = "".join(ch for ch in title if not ch.isspace())
    compact_context = "".join(ch for ch in context if not ch.isspace())
    if not compact_title:
        return False
    return compact_title[:12] in compact_context or compact_context[:12] in compact_title

