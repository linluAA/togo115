from __future__ import annotations

import asyncio

from telethon import TelegramClient

from app.services.adapters.telegram.bot.adapter import TelegramBotAdapter
from app.services.adapters.telegram.history.search import TelegramHistorySearchMixin
from app.services.adapters.telegram.monitor import TelegramMonitorMixin
from app.services.adapters.telegram.scan.scanner import TelegramMessageScanner
from app.services.adapters.telegram.session.mixin import TelegramSessionMixin


class TelegramClientAdapter(
    TelegramSessionMixin,
    TelegramHistorySearchMixin,
    TelegramMonitorMixin,
    TelegramMessageScanner,
):
    _client: TelegramClient | None = None
    _client_loop: asyncio.AbstractEventLoop | None = None
    _listener_task: asyncio.Task | None = None
    _handler_registered: bool = False
    _handler = None
    _handler_sources: tuple[str, ...] = ()


__all__ = ["TelegramBotAdapter", "TelegramClientAdapter"]
