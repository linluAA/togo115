from __future__ import annotations

from typing import Any

from telethon import utils

from app.services.adapters.telegram.session.dialog_store import (
    upsert_dialog_entities,
    upsert_dialog_entity,
)


class TelegramDialogKeysMixin:
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

    def _entity_snapshot(self, entity: Any, source: str, title: str | None = None) -> dict[str, Any]:
        peer_id = self._entity_source_id(entity, source)
        entity_type = "channel" if getattr(entity, "broadcast", False) else "group" if getattr(entity, "megagroup", False) else "peer"
        return {
            "source": str(source),
            "peer_id": peer_id,
            "entity_id": str(getattr(entity, "id", "") or "") or None,
            "access_hash": str(getattr(entity, "access_hash", "") or "") or None,
            "username": str(getattr(entity, "username", "") or "") or None,
            "title": str(title or getattr(entity, "title", "") or "") or None,
            "entity_type": entity_type,
        }

    def _persist_entity(self, entity: Any, source: str, title: str | None = None) -> None:
        try:
            upsert_dialog_entity(**self._entity_snapshot(entity, source, title))
        except Exception as exc:
            add_log("debug", "telegram", "Telegram 来源映射落库失败", {"source": source, "error": str(exc)})

    def _persist_entity_map(self, items: dict[str, dict[str, Any]]) -> None:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items.values():
            entity = item.get("entity")
            if entity is None:
                continue
            source = str(item.get("canonical") or item.get("source") or "")
            if not source or source in seen:
                continue
            seen.add(source)
            rows.append(self._entity_snapshot(entity, source, item.get("title")))
        try:
            upsert_dialog_entities(rows)
        except Exception as exc:
            add_log("debug", "telegram", "Telegram 会话映射批量落库失败", {"count": len(rows), "error": str(exc)})

    def _dialog_item(self, dialog) -> dict[str, Any] | None:
        entity = dialog.entity
        if not (getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False)):
            return None
        identifier = self._entity_source_id(entity, str(getattr(entity, "id", "")))
        self._persist_entity(entity, identifier, dialog.name)
        return {
            "id": str(entity.id),
            "title": dialog.name,
            "username": getattr(entity, "username", None),
            "source": identifier,
            "type": "频道" if getattr(entity, "broadcast", False) else "群组",
        }
