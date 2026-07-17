from __future__ import annotations

import asyncio
import re
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.link import (
    TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS,
    _local_text_matches_query,
    _looks_like_context_message,
    _looks_like_link_only_message,
    _message_has_link_button_hint,
    _nearby_link_text_matches,
    extract_115_links,
    telegram_message_text,
)


class TelegramMessageContextMixin:
    async def _related_messages_for_link_scan(
        self,
        client: TelegramClient | None,
        message: Any,
        entity: Any = None,
        match_queries: list[str] | None = None,
    ) -> list[Any]:
        collector = _RelatedMessageCollector()
        collector.add(message)
        siblings = await self._neighbor_messages(client, message, entity)
        if not siblings:
            return collector.messages

        base_id = getattr(message, "id", None)
        grouped_id = getattr(message, "grouped_id", None)
        base_text = telegram_message_text(message)
        base_matches_query = any(_local_text_matches_query(base_text, query) for query in match_queries or [])
        base_has_link_or_button = bool(extract_115_links(base_text) or _message_has_link_button_hint(message))
        context_candidates = self._context_candidates(base_id, siblings, base_has_link_or_button, match_queries)

        for sibling in siblings:
            if self._should_merge_sibling(message, sibling, base_matches_query, match_queries):
                collector.add(sibling)

        context_added = 0
        for _, sibling in sorted(context_candidates, key=lambda item: item[0])[:2]:
            if collector.add(sibling):
                context_added += 1
        if context_added:
            add_log("debug", "telegram", "Telegram 链接消息已合并相邻标题上下文", {"message_id": base_id, "context_messages": context_added})
        return collector.messages

    def _should_merge_sibling(self, message: Any, sibling: Any, base_matches_query: bool, match_queries: list[str] | None) -> bool:
        if not sibling or getattr(sibling, "id", None) == getattr(message, "id", None):
            return False
        sibling_text = telegram_message_text(sibling)
        same_group = self._same_message_group(message, sibling)
        sibling_has_button = _message_has_link_button_hint(sibling)
        if same_group:
            return True
        # Only merge a sibling share when its own text matches the query, or it is an
        # immediately adjacent link-only / button prompt belonging to the matched card.
        if _nearby_link_text_matches(sibling_text, match_queries):
            return True
        distance = self._message_distance(getattr(message, "id", None), getattr(sibling, "id", None))
        if base_matches_query and distance == 1 and extract_115_links(sibling_text) and _looks_like_link_only_message(sibling_text):
            return True
        return bool(base_matches_query and sibling_has_button and self._button_sibling_belongs_to_base(message, sibling, match_queries))

    def _button_sibling_belongs_to_base(self, message: Any, sibling: Any, match_queries: list[str] | None) -> bool:
        distance = self._message_distance(getattr(message, "id", None), getattr(sibling, "id", None))
        if distance > 2:
            return False
        sibling_text = telegram_message_text(sibling).strip()
        if not sibling_text:
            return True
        if _nearby_link_text_matches(sibling_text, match_queries):
            return True
        if any(_local_text_matches_query(sibling_text, query) for query in match_queries or []):
            return True
        # 只允许相邻的纯按钮/短提示消息并入当前命中消息，避免把相邻资源卡片的按钮误当成当前订阅链接。
        return self._looks_like_button_prompt(sibling_text)

    def _looks_like_button_prompt(self, text: str) -> bool:
        compact_hint = re.sub(r"\s+", "", str(text or ""))
        if not compact_hint or len(compact_hint) > 16:
            return False
        if re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)|S\d{1,2}E\d{1,3}|E\d{1,3}", compact_hint, re.I):
            return False
        return any(word in compact_hint.casefold() for word in ("\u70b9\u51fb", "\u67e5\u770b", "\u8d44\u6e90", "\u94fe\u63a5", "\u9886\u53d6", "\u83b7\u53d6", "\u6253\u5f00", "115", "link"))

    def _context_candidates(
        self,
        base_id: Any,
        siblings: list[Any],
        base_has_link_or_button: bool,
        match_queries: list[str] | None,
    ) -> list[tuple[int, Any]]:
        if not base_has_link_or_button or match_queries:
            return []
        candidates: list[tuple[int, Any]] = []
        for sibling in siblings:
            sibling_text = telegram_message_text(sibling)
            if _looks_like_context_message(sibling_text):
                distance = self._message_distance(base_id, getattr(sibling, "id", None))
                if 0 < distance <= 4:
                    candidates.append((distance, sibling))
        return candidates

    async def _neighbor_messages(self, client: TelegramClient | None, message: Any, entity: Any = None) -> list[Any]:
        message_id = getattr(message, "id", None)
        if not client or not message_id:
            return []
        ids = list(range(max(1, int(message_id) - 8), int(message_id) + 9))
        last_error = ""
        for peer in self._message_peer_candidates(message, entity):
            try:
                siblings = await asyncio.wait_for(client.get_messages(peer, ids=ids), timeout=TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS)
                return siblings if isinstance(siblings, list) else [siblings]
            except asyncio.TimeoutError:
                last_error = f"timeout {TELEGRAM_MESSAGE_FETCH_TIMEOUT_SECONDS}s"
            except Exception as exc:
                last_error = str(exc)
        add_log("debug", "telegram", "Telegram 相邻消息读取失败", {"message_id": message_id, "error": last_error})
        return []

    def _message_peer_candidates(self, message: Any, entity: Any = None) -> list[Any]:
        candidates = [entity, getattr(message, "input_chat", None), getattr(message, "chat", None), getattr(message, "peer_id", None), getattr(message, "chat_id", None)]
        peers: list[Any] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate:
                continue
            key = f"{type(candidate).__name__}:{candidate}"
            if key not in seen:
                seen.add(key)
                peers.append(candidate)
        return peers

    def _same_message_group(self, left: Any, right: Any) -> bool:
        left_grouped_id = getattr(left, "grouped_id", None)
        right_grouped_id = getattr(right, "grouped_id", None)
        return bool(left_grouped_id and right_grouped_id and str(left_grouped_id) == str(right_grouped_id))

    def _message_distance(self, left: Any, right: Any) -> int:
        try:
            return abs(int(left) - int(right))
        except (TypeError, ValueError):
            return 99


class _RelatedMessageCollector:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self._seen_ids: set[str] = set()

    def add(self, value: Any) -> bool:
        if not value:
            return False
        key = str(getattr(value, "id", None) or id(value))
        if key in self._seen_ids:
            return False
        self._seen_ids.add(key)
        self.messages.append(value)
        return True
