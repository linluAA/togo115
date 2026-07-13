from __future__ import annotations

from typing import Any

from app.services.adapters.telegram_bot_callbacks import TelegramBotCallbackMixin
from app.services.adapters.telegram_bot_commands import TelegramBotCommandMixin
from app.services.adapters.telegram_bot_messages import TelegramBotMessageMixin
from app.services.adapters.telegram_bot_polling import TelegramBotPollingMixin
from app.services.integration_state import get_setting


class TelegramBotAdapter(
    TelegramBotPollingMixin,
    TelegramBotCallbackMixin,
    TelegramBotMessageMixin,
    TelegramBotCommandMixin,
):
    def _config(self) -> dict[str, Any]:
        return get_setting("tg_bot")

    def _api_url(self, token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    def _chat_allowed(self, config: dict[str, Any], chat_id: int | str | None) -> bool:
        allowed = str(config.get("allowed_chat_id") or "").strip()
        return not allowed or str(chat_id) == allowed
