from __future__ import annotations

from typing import Any

from app.services.link import (
    local_text_matches_query,
    message_has_link_button_hint,
    nearby_recent_messages_have_button_hint,
    text_has_external_resource_page_hint,
    telegram_message_text,
)


class TelegramRecentWindowMixin:
    def _matched_recent_queries(self, message: Any, queries: list[str]) -> list[str]:
        return self._matched_recent_queries_in_text(telegram_message_text(message), queries)

    def _matched_recent_queries_in_text(self, text: str, queries: list[str]) -> list[str]:
        return [query for query in queries if local_text_matches_query(text, query)]

    def _recent_window_messages(self, messages: list[Any], index: int, window: int = 4) -> list[Any]:
        return [messages[item_index] for item_index in range(max(0, index - window), min(len(messages), index + window + 1)) if item_index != index]

    def _recent_window_texts(self, window_messages: list[Any], base_message: Any) -> list[str]:
        texts: list[str] = []
        seen: set[str] = {telegram_message_text(base_message)}
        for item in window_messages:
            text = telegram_message_text(item)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return texts

    def _recent_link_anchor(self, message: Any, window_messages: list[Any], window_texts: list[str]) -> Any | None:
        if self._message_has_link_hint(message):
            return message
        for item in window_messages:
            if self._message_has_link_hint(item):
                return item
        return message if any(extract_115_links(text) or text_has_external_resource_page_hint(text) for text in window_texts) else None

    def _recent_message_has_link_hint(self, message: Any, nearby_texts: list[str], recent_messages: list[Any], index: int) -> bool:
        text = telegram_message_text(message)
        return bool(
            extract_115_links(text)
            or any(extract_115_links(item) for item in nearby_texts)
            or text_has_external_resource_page_hint(text)
            or any(text_has_external_resource_page_hint(item) for item in nearby_texts)
            or message_has_link_button_hint(message)
            or nearby_recent_messages_have_button_hint(recent_messages, index)
        )

    def _message_has_link_hint(self, message: Any) -> bool:
        text = telegram_message_text(message)
        return bool(extract_115_links(text) or text_has_external_resource_page_hint(text) or message_has_link_button_hint(message))

