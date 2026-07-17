from __future__ import annotations

import asyncio
import time
from typing import Any

from telethon import TelegramClient

from app.db import add_log
from app.services.adapters.telegram.session.dialog_keys import TelegramDialogKeysMixin
from app.services.adapters.telegram.session.dialog_store import load_dialog_entity_rows

TELEGRAM_DIALOG_CACHE_TTL_SECONDS = 300


class TelegramDialogsMixin(TelegramDialogKeysMixin):
    _dialog_entity_map_cache: dict[str, dict[str, dict[str, Any]]] = {}
    _dialog_entity_map_cache_at: dict[str, float] = {}

    async def _resolve_from_persistent_cache(self, client: TelegramClient, source: str) -> dict[str, Any] | None:
        try:
            rows = load_dialog_entity_rows([source, *self._dialog_lookup_keys(source)])
        except Exception:
            return None
        if not rows:
            # Also try peer_id match by scanning all keys loosely.
            try:
                all_rows = load_dialog_entity_rows()
            except Exception:
                return None
            wanted = self._dialog_lookup_keys(source)
            rows = [row for row in all_rows if wanted.intersection(self._dialog_lookup_keys(str(row.get("source") or "")) | self._dialog_lookup_keys(str(row.get("peer_id") or "")) | self._dialog_lookup_keys(str(row.get("username") or "")))]
        for row in rows:
            entity = await self._entity_from_row(client, row)
            if entity is None:
                continue
            canonical = self._entity_source_id(entity, str(row.get("peer_id") or source))
            return {"entity": entity, "source": source, "canonical": canonical}
        return None

    async def _entity_from_row(self, client: TelegramClient, row: dict[str, Any]) -> Any | None:
        candidates: list[Any] = []
        username = str(row.get("username") or "").strip()
        peer_id = str(row.get("peer_id") or "").strip()
        entity_id = str(row.get("entity_id") or "").strip()
        if username:
            candidates.append(username if not username.startswith("@") else username[1:])
            candidates.append(f"@{username.lstrip('@')}")
        for value in (peer_id, entity_id):
            if not value:
                continue
            candidates.append(value)
            try:
                candidates.append(int(value))
            except ValueError:
                pass
        for candidate in self._dedupe_dialog_candidates(candidates):
            try:
                return await asyncio.wait_for(client.get_entity(candidate), timeout=4)
            except Exception:
                continue
        return None

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
                item = {
                    "entity": entity,
                    "source": canonical,
                    "canonical": canonical,
                    "title": getattr(dialog, "name", None),
                }
                for key in self._entity_lookup_keys(entity, getattr(dialog, "name", None)):
                    items[key] = item

        await asyncio.wait_for(collect(), timeout=15)
        self._store_dialog_entity_map(cache_key, items)
        self._persist_entity_map(items)
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
                entity = matched.get("entity")
                if entity is not None:
                    self._persist_entity(entity, str(matched.get("canonical") or source), matched.get("title"))
                continue
            persisted = await self._resolve_from_persistent_cache(client, source)
            if persisted is not None:
                dialogs.append(persisted)
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
        canonical = self._entity_source_id(entity, source)
        self._persist_entity(entity, canonical, getattr(entity, "title", None))
        return {"entity": entity, "source": source, "canonical": canonical}

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
