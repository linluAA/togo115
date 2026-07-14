from __future__ import annotations

from app.services.adapters.telegram.session.dialogs import TelegramDialogsMixin
from app.services.adapters.telegram.session.login import TelegramLoginMixin
from app.services.adapters.telegram.session.config import TelegramSessionConfigMixin


class TelegramSessionMixin(
    TelegramLoginMixin,
    TelegramDialogsMixin,
    TelegramSessionConfigMixin,
):
    pass
