from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient, utils

from app.db import add_log

TELEGRAM_DIALOG_CACHE_TTL_SECONDS = 300


class _TelegramDialogsMixin:
    _dialog_entity_map_cache: dict[str, dict[str, dict[str, Any]]] = {}
    _dialog_entity_map_cache_at: dict[str, float] = {}

    def _dialog_candidates(self, source: str) -> list[Any]:
        value = str(source or "").strip()
        if not value:
            return []
        candidates: list[Any] = [value[1:] if value.startswith("@") else value, value]
        try:
            numeric = int(value)
        except ValueError:
            numeric = None
        if numeric is not None:
            candidates.append(numeric)
            if numeric > 0:
                candidates.append(int(f"-100{numeric}"))
            elif value.startswith("-100") and len(value) > 4:
                try:
                    candidates.append(int(value[4:]))
                except ValueError:
                    pass
        return self._dedupe_dialog_candidates(candidates)

    def _dedupe_dialog_candidates(self, candidates: list[Any]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = f"{type(candidate).__name__}:{candidate}"
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return deduped

    def _entity_source_id(self, entity: Any, fallback: str) -> str:
        try:
            return str(utils.get_peer_id(entity))
        except Exception:
            return str(getattr(entity, "id", None) or fallback)

    def _dialog_lookup_keys(self, source: str) -> set[str]:
        keys: set[str] = set()
        value = str(source or "").strip().strip("[]'\" ")
        if not value:
            return keys
        keys.add(value)
        keys.add(value.lower())
        if value.startswith("@"):
            keys.add(value[1:].lower())
        try:
            numeric = int(value)
        except ValueError:
            numeric = None
        if numeric is not None:
            keys.add(str(numeric))
            if numeric > 0:
                keys.add(str(-int(f"100{numeric}")))
                keys.add(str(int(f"-100{numeric}")))
            elif value.startswith("-100") and len(value) > 4:
                keys.add(value[4:])
        return keys

    def _entity_lookup_keys(self, entity: Any, title: str | None = None) -> set[str]:
        keys: set[str] = set()
        for value in (
            getattr(entity, "id", None),
            getattr(entity, "username", None),
            self._entity_source_id(entity, ""),
            title,
        ):
            text = str(value or "").strip()
            if not text:
                continue
            keys.add(text)
            keys.add(text.lower())
            if text.startswith("@"):
                keys.add(text[1:].lower())
        return keys

    async def _dialog_entity_map(self, client: TelegramClient) -> dict[str, dict[str, Any]]:
        cache_key = self._dialog_cache_key(client)
        cached = self._cached_dialog_entity_map(cache_key)
        if cached is not None:
            return cached
        items: dict[str, dict[str, Any]] = {}

        async def collect() -> None:
            async for dialog in client.iter_dialogs():
                entity = getattr(dialog, "entity", None)
                if entity is None:
                    continue
                if not (getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False)):
                    continue
                canonical = self._entity_source_id(entity, str(getattr(entity, "id", "")))
                item = {"entity": entity, "source": canonical, "canonical": canonical}
                for key in self._entity_lookup_keys(entity, getattr(dialog, "name", None)):
                    items[key] = item

        await asyncio.wait_for(collect(), timeout=15)
        self._store_dialog_entity_map(cache_key, items)
        return items

    def _dialog_cache_key(self, client: TelegramClient) -> str:
        return f"{id(asyncio.get_running_loop())}:{id(client)}"

    def _cached_dialog_entity_map(self, cache_key: str) -> dict[str, dict[str, Any]] | None:
        cached_at = self._dialog_entity_map_cache_at.get(cache_key)
        if not cached_at or time.monotonic() - cached_at > TELEGRAM_DIALOG_CACHE_TTL_SECONDS:
            return None
        cached = self._dialog_entity_map_cache.get(cache_key)
        return dict(cached) if cached is not None else None

    def _store_dialog_entity_map(self, cache_key: str, items: dict[str, dict[str, Any]]) -> None:
        cls = type(self)
        cls._dialog_entity_map_cache = {cache_key: dict(items)}
        cls._dialog_entity_map_cache_at = {cache_key: time.monotonic()}

    async def _resolve_dialogs(self, client: TelegramClient, sources: list[str]) -> list[dict[str, Any]]:
        dialogs: list[dict[str, Any]] = []
        dialog_map: dict[str, dict[str, Any]] = {}
        try:
            dialog_map = await self._dialog_entity_map(client)
        except asyncio.TimeoutError:
            add_log("warning", "telegram", "Telegram 会话列表读取超时，继续逐个解析来源", {"sources": len(sources), "timeout": 15})
        except Exception as exc:
            add_log("warning", "telegram", "Telegram 会话列表读取失败，继续逐个解析来源", {"sources": len(sources), "error": str(exc)})
        for source in sources:
            matched = None
            for key in self._dialog_lookup_keys(source):
                matched = dialog_map.get(key)
                if matched:
                    break
            if matched:
                dialogs.append({**matched, "source": source})
                continue
            dialogs.append(await self._resolve_dialog(client, source))
        return dialogs

    async def _resolve_dialog(self, client: TelegramClient, source: str) -> dict[str, Any]:
        entity = None
        last_error: Exception | None = None
        for candidate in self._dialog_candidates(source):
            try:
                entity = await asyncio.wait_for(client.get_entity(candidate), timeout=6)
                break
            except asyncio.TimeoutError as exc:
                last_error = exc
                add_log("debug", "telegram", "Telegram 来源解析单个候选超时", {"source": source, "candidate": str(candidate), "timeout": 6})
            except Exception as exc:
                last_error = exc
        if entity is None:
            add_log(
                "warning",
                "telegram",
                "Telegram 群组/频道解析失败，使用原始配置尝试",
                {"source": source, "error": str(last_error) if last_error else ""},
            )
            return {"entity": source, "source": source, "canonical": source}
        return {"entity": entity, "source": source, "canonical": self._entity_source_id(entity, source)}

    async def dialogs(self) -> list[dict[str, Any]]:
        client = await self.client()
        if not await client.is_user_authorized():
            return []
        items: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs():
            item = self._dialog_item(dialog)
            if item:
                items.append(item)
        return items

    def _dialog_item(self, dialog) -> dict[str, Any] | None:
        entity = dialog.entity
        if not (getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False)):
            return None
        identifier = self._entity_source_id(entity, str(getattr(entity, "id", "")))
        return {
            "id": str(entity.id),
            "title": dialog.name,
            "username": getattr(entity, "username", None),
            "source": identifier,
            "type": "频道" if getattr(entity, "broadcast", False) else "群组",
        }
