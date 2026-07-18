from __future__ import annotations

from typing import Any

from telethon import TelegramClient

from app.services.adapters.telegram.scan.extract_cache import (
    get_cached_message_extract,
    set_cached_message_extract,
)
from app.services.adapters.telegram.models import TelegramSearchBudget
from app.services.adapters.telegram.pipeline import TelegramPipelineStats
from app.services.link import (
    TELEGRAM_BUTTON_CLICK_MAX_PER_MESSAGE,
    TELEGRAM_BUTTON_CLICK_TIMEOUT_SECONDS,
    extract_115_links,
    local_text_matches_query,
    telegram_message_text,
)
from app.services.types import SearchResult


class TelegramFastMessageMixin:
    async def _fast_links_from_message(
        self,
        client: TelegramClient,
        entity: Any,
        source: str,
        message: Any,
        queries: list[str],
    ) -> list[SearchResult]:
        message_id = getattr(message, "id", None)
        cached = get_cached_message_extract(source, message_id)
        if cached is not None:
            return self._filter_cached_results_by_query(list(cached), queries)

        texts = [telegram_message_text(message)]
        # Prefer current message first; only scan neighbors/buttons if no direct 115 link.
        link_contexts = self._fast_link_contexts(texts[0] if texts else "")
        if not link_contexts:
            texts.extend(await self._fast_neighbor_texts(client, entity, message))
            link_contexts = self._fast_link_contexts("\n".join(text for text in texts if text))
        if not link_contexts:
            link_contexts.update(await self._fast_button_link_contexts(message, client, entity, texts))

        # Cache unfiltered extract; query filtering is applied per search.
        unfiltered = self._search_results_from_contexts(message, source, link_contexts)
        set_cached_message_extract(source, message_id, unfiltered)
        if not queries:
            return unfiltered
        filtered = self._filter_cached_results_by_query(unfiltered, queries)
        return filtered

    def _filter_cached_results_by_query(self, results: list[SearchResult], queries: list[str] | None) -> list[SearchResult]:
        if not queries:
            return results
        filtered = [
            result
            for result in results
            if any(self.local_text_matches_query_safe(result.context or result.title, query) for query in queries)
        ]
        return filtered or results

    def local_text_matches_query_safe(self, text: str | None, query: str | None) -> bool:
        try:
            from app.services.link import local_text_matches_query

            return bool(local_text_matches_query(text, query))
        except Exception:
            return True

    async def _fast_neighbor_texts(self, client: TelegramClient, entity: Any, message: Any) -> list[str]:
        message_id = int(getattr(message, "id", 0) or 0)
        if not message_id:
            return []
        ids = list(range(max(1, message_id - 3), message_id + 4))
        try:
            siblings = await asyncio.wait_for(client.get_messages(entity, ids=ids), timeout=TELEGRAM_FAST_NEIGHBOR_TIMEOUT_SECONDS)
        except Exception:
            return []
        items = siblings if isinstance(siblings, list) else [siblings]
        return [telegram_message_text(item) for item in items if item and getattr(item, "id", None) != getattr(message, "id", None)]

    def _fast_link_contexts(self, text: str) -> dict[str, str]:
        links = extract_115_links(text)
        return {link: context_for_115_link(text, link, len(links)) for link in links}

    async def _fast_button_link_contexts(self, message: Any, client: TelegramClient, entity: Any, texts: list[str]) -> dict[str, str]:
        contexts: dict[str, str] = {}
        base_text = "\n".join(text for text in texts if text)
        clicked = 0
        for row_index, row in enumerate(getattr(message, "buttons", None) or []):
            for col_index, button in enumerate(row):
                contexts.update(self._fast_button_value_contexts(button, base_text))
                if contexts or clicked >= 1 or not self._button_should_click(self._fast_button_values(button)):
                    continue
                clicked += 1
                contexts.update(await self._fast_click_button_for_context(message, row_index, col_index, getattr(button, "text", "") or "", base_text, client, entity))
        return contexts

    def _fast_button_value_contexts(self, button: Any, base_text: str) -> dict[str, str]:
        contexts: dict[str, str] = {}
        label = getattr(button, "text", "") or ""
        for value in self._fast_button_values(button):
            text = "\n".join(part for part in (base_text, label, str(value or "")) if part)
            contexts.update(self._fast_link_contexts(text))
        return contexts

    def _fast_button_values(self, button: Any) -> list[Any]:
        raw_button = getattr(button, "button", None)
        return [getattr(button, "text", "") or "", getattr(button, "url", None), getattr(raw_button, "url", None)]

    async def _fast_click_button_for_context(
        self,
        message: Any,
        row_index: int,
        col_index: int,
        label: str,
        base_text: str,
        client: TelegramClient,
        entity: Any,
    ) -> dict[str, str]:
        try:
            response = await asyncio.wait_for(message.click(row_index, col_index), timeout=TELEGRAM_FAST_BUTTON_CLICK_TIMEOUT_SECONDS)
        except Exception:
            return {}
        text = "\n".join(part for part in (base_text, label, getattr(response, "url", None), telegram_message_text(response)) if part)
        contexts = self._fast_link_contexts(text)
        if contexts:
            return contexts
        try:
            refreshed = await asyncio.wait_for(client.get_messages(entity, ids=[getattr(message, "id", 0)]), timeout=0.35)
        except Exception:
            return {}
        items = refreshed if isinstance(refreshed, list) else [refreshed]
        return self._fast_link_contexts("\n".join([text, *(telegram_message_text(item) for item in items if item)]))
