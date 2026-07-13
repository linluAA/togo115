from __future__ import annotations

from app.services.subscription_chinese_numbers import _chinese_number_to_int


def _number_token_to_int(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _chinese_number_to_int(text)
