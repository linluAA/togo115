from __future__ import annotations

from app.services.adapters.telegram.scan.button_links import TelegramButtonLinkMixin
from app.services.adapters.telegram.scan.message_context import TelegramMessageContextMixin
from app.services.adapters.telegram.scan.message_links import TelegramMessageLinkMixin


class TelegramMessageScanner(
    TelegramMessageLinkMixin,
    TelegramMessageContextMixin,
    TelegramButtonLinkMixin,
):
    pass
