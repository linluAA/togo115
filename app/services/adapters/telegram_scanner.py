from __future__ import annotations

from app.services.adapters.telegram_button_links import _TelegramButtonLinkMixin
from app.services.adapters.telegram_message_context import _TelegramMessageContextMixin
from app.services.adapters.telegram_message_links import _TelegramMessageLinkMixin


class _TelegramMessageScanner(
    _TelegramMessageLinkMixin,
    _TelegramMessageContextMixin,
    _TelegramButtonLinkMixin,
):
    pass
