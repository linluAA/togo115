from __future__ import annotations

from typing import Any

from app.db import add_log
from app.services.adapters.telegram import TelegramBotAdapter


async def notify_subscription_completed(subscription: dict[str, Any]) -> bool:
    """Notify Telegram Bot when a subscription is automatically completed."""
    try:
        return await TelegramBotAdapter().send_subscription_completed_notification(subscription)
    except Exception as exc:
        add_log(
            "warning",
            "tg_bot",
            "订阅完成通知发送失败",
            {"id": subscription.get("id"), "title": subscription.get("title"), "error": str(exc), "error_type": type(exc).__name__},
        )
        return False
