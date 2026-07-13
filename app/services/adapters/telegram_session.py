from __future__ import annotations

from app.services.adapters.telegram_dialogs import _TelegramDialogsMixin
from app.services.adapters.telegram_login import _TelegramLoginMixin
from app.services.adapters.telegram_session_config import _TelegramSessionConfigMixin
from app.services.adapters.telegram_webapp import _TelegramWebAppMixin


class _TelegramSessionMixin(
    _TelegramLoginMixin,
    _TelegramDialogsMixin,
    _TelegramWebAppMixin,
    _TelegramSessionConfigMixin,
):
    pass
