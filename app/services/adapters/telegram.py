from __future__ import annotations

import asyncio

from telethon import TelegramClient

from app.services.adapters.telegram_bot import TelegramBotAdapter
from app.services.adapters.telegram_history import _TelegramHistorySearchMixin
from app.services.adapters.telegram_monitor import _TelegramMonitorMixin
from app.services.adapters.telegram_scanner import _TelegramMessageScanner
from app.services.adapters.telegram_session import _TelegramSessionMixin


class TelegramClientAdapter(
    _TelegramSessionMixin,
    _TelegramHistorySearchMixin,
    _TelegramMonitorMixin,
    _TelegramMessageScanner,
):
    _client: TelegramClient | None = None
    _client_loop: asyncio.AbstractEventLoop | None = None
    _listener_task: asyncio.Task | None = None
    _handler_registered: bool = False
    _handler = None
    _handler_sources: tuple[str, ...] = ()


__all__ = ["TelegramBotAdapter", "TelegramClientAdapter"]
