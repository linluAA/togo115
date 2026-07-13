from __future__ import annotations

import asyncio
import unittest

import httpx

from app.services.adapters.telegram_bot_polling import TelegramBotPollingMixin


class BotPollingHarness(TelegramBotPollingMixin):
    def _config(self) -> dict:
        return {"bot_token": "token"}

    def _api_url(self, token: str, method: str) -> str:
        return f"https://api.telegram.test/bot{token}/{method}"

    def _chat_allowed(self, config: dict, chat_id: int | str | None) -> bool:
        return True


class TelegramBotPollingTest(unittest.IsolatedAsyncioTestCase):
    def test_timeout_payload_keeps_error_type_when_message_is_empty(self) -> None:
        bot = BotPollingHarness()
        exc = httpx.ReadTimeout("")

        payload = bot._poll_error_payload(exc, action="retry-poll", recovered=True, retry_delay=2)

        self.assertEqual(payload["category"], "timeout")
        self.assertEqual(payload["error_type"], "ReadTimeout")
        self.assertIn("ReadTimeout", payload["error_repr"])
        self.assertEqual(payload["action"], "retry-poll")
        self.assertTrue(payload["recovered"])

    def test_polling_conflict_is_classified_from_api_payload(self) -> None:
        bot = BotPollingHarness()

        payload = bot._api_error_payload({"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"})

        self.assertEqual(payload["category"], "polling-conflict")
        self.assertEqual(payload["error_type"], "TelegramApiError")
        self.assertTrue(payload["recovered"])


    def test_recoverable_poll_error_is_throttled_after_first_warning(self) -> None:
        class LocalHarness(BotPollingHarness):
            _poll_warning_last_seen = {}

        bot = LocalHarness()

        self.assertFalse(bot._should_throttle_recoverable_poll_error("timeout", "retry-poll"))
        self.assertTrue(bot._should_throttle_recoverable_poll_error("timeout", "retry-poll"))
        self.assertFalse(bot._should_throttle_recoverable_poll_error("auth-or-token", "retry-poll"))

    def test_http_502_is_recoverable_telegram_api_error(self) -> None:
        bot = BotPollingHarness()
        request = httpx.Request("GET", "https://api.telegram.org/bot" + "1234567890:" + "abcdefghijklmnopqrstuvwxyzABCDEFGH" + "/getUpdates")
        response = httpx.Response(502, request=request)
        exc = httpx.HTTPStatusError("bad gateway", request=request, response=response)

        payload = bot._poll_error_payload(exc, action="retry-poll", recovered=True, retry_delay=3)

        self.assertEqual(payload["category"], "telegram-api")
        self.assertEqual(payload["error_type"], "HTTPStatusError")

    async def test_ensure_polling_restarts_done_task(self) -> None:
        class LocalHarness(BotPollingHarness):
            _polling_task = None
            _polling_token = None

            async def _poll_updates(self, token: str) -> None:
                await asyncio.sleep(10)

        bot = LocalHarness()
        old_task = asyncio.create_task(asyncio.sleep(0))
        await old_task
        LocalHarness._polling_task = old_task
        LocalHarness._polling_token = "token"

        await bot.ensure_polling()

        self.assertIsNot(LocalHarness._polling_task, old_task)
        self.assertFalse(LocalHarness._polling_task.done())
        await bot.stop_polling()
