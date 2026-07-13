from __future__ import annotations

from typing import Any


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _text_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _add_text_part(parts: list[str], seen: set[str], value: Any) -> None:
    text = _text_part(value)
    if text and text not in seen:
        seen.add(text)
        parts.append(text)


def _collect_dict_texts(value: Any, parts: list[str], seen: set[str], depth: int = 0) -> None:
    if depth > 5 or value is None:
        return
    if isinstance(value, str | bytes):
        _add_text_part(parts, seen, value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").casefold()
            if key_text in ("message", "text", "caption", "raw_text", "url", "display_url", "title", "description", "site_name") or isinstance(item, (dict, list, tuple)):
                _collect_dict_texts(item, parts, seen, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_dict_texts(item, parts, seen, depth + 1)


def telegram_message_text(message: Any) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        _add_text_part(parts, seen, value)

    for attr in ("raw_text", "message", "text", "caption"):
        add(_safe_attr(message, attr))
    for entity in _safe_attr(message, "entities") or []:
        add(_safe_attr(entity, "url"))
    _add_entities_text(message, add)
    _add_web_preview_text(message, add)
    _add_serialized_message_text(message, add, parts, seen)
    return "\n".join(parts)


def _add_entities_text(message: Any, add) -> None:
    get_entities_text = _safe_attr(message, "get_entities_text")
    if not callable(get_entities_text):
        return
    try:
        for entity, text in get_entities_text():
            add(text)
            add(_safe_attr(entity, "url"))
    except Exception:
        pass


def _add_web_preview_text(message: Any, add) -> None:
    for container in (_safe_attr(message, "media"), _safe_attr(message, "web_preview")):
        if not container:
            continue
        webpage = _safe_attr(container, "webpage") or container
        for attr in ("url", "display_url", "site_name", "title", "description"):
            add(_safe_attr(webpage, attr))


def _add_serialized_message_text(message: Any, add, parts: list[str], seen: set[str]) -> None:
    to_dict = _safe_attr(message, "to_dict")
    if callable(to_dict):
        try:
            _collect_dict_texts(to_dict(), parts, seen)
        except Exception:
            pass
    for method_name in ("to_json", "stringify"):
        method = _safe_attr(message, method_name)
        if callable(method):
            try:
                add(method())
            except Exception:
                pass
