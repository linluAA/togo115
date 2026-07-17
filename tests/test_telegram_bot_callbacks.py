from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.adapters.telegram.bot.callbacks import TelegramBotCallbackMixin
from app.services.adapters.telegram.bot.messages import TelegramBotMessageMixin
from app.services.sources.rss_torznab import SearchResult
from app.services.magnet import magnet_results_reply_markup


class FakeResponse:
    status_code = 200
    text = "ok"


class FakeClient:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, url: str, data: dict) -> FakeResponse:
        self.posts.append({"url": url, "data": data})
        return FakeResponse()


class BotCallbackHarness(TelegramBotCallbackMixin, TelegramBotMessageMixin):
    def _config(self) -> dict:
        return {}

    def _api_url(self, token: str, method: str) -> str:
        return f"https://api.telegram.test/bot{token}/{method}"

    def _chat_allowed(self, config: dict, chat_id: int | str | None) -> bool:
        return True


class TelegramBotCallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_magnet_choice_replaces_options_with_searching_message(self) -> None:
        bot = BotCallbackHarness()
        client = FakeClient()
        callback = {
            "id": "callback-1",
            "data": "magnet:tv:123",
            "message": {"message_id": 99, "chat": {"id": 456}},
        }

        with (
            patch(
                "app.services.adapters.telegram.bot.callbacks.search_magnets_for_tmdb",
                return_value=({"name": "斗罗大陆"}, [{"title": "斗罗大陆 S01", "link": "magnet:?xt=urn:btih:abc"}]),
            ) as search_mock,
            patch(
                "app.services.adapters.telegram.bot.callbacks.magnet_results_reply",
                return_value="搜索完成：斗罗大陆",
            ),
        ):
            await bot._handle_callback(client, "token", callback)

        methods = [post["url"].rsplit("/", 1)[-1] for post in client.posts]
        self.assertEqual(methods[:2], ["answerCallbackQuery", "editMessageText"])
        self.assertIn("正在搜索磁力", client.posts[1]["data"]["text"])
        self.assertEqual(client.posts[1]["data"]["reply_markup"], '{"inline_keyboard":[]}')
        self.assertEqual(client.posts[2]["url"].rsplit("/", 1)[-1], "sendMessage")
        self.assertEqual(client.posts[2]["data"]["text"], "搜索完成：斗罗大陆")
        search_mock.assert_awaited_once_with("tv", 123)

    async def test_magnet_pick_tries_next_candidate_after_delivery_failure(self) -> None:
        bot = BotCallbackHarness()
        results = [
            SearchResult(title="候选1", url="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", source="site_plugin:test"),
            SearchResult(title="候选2", url="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", source="site_plugin:test"),
        ]
        markup = magnet_results_reply_markup({"title": "测试", "media_type": "movie"}, results)
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]
        client = FakeClient()
        callback = {
            "id": "callback-2",
            "data": callback_data,
            "message": {"message_id": 100, "chat": {"id": 456}},
        }

        with patch.object(bot, "_deliver_magnet_pick", AsyncMock(side_effect=[(False, "失败"), (True, "")])) as deliver:
            await bot._handle_callback(client, "token", callback)

        self.assertEqual(deliver.await_count, 2)
        self.assertIn("第 2 个候选", client.posts[-1]["data"]["text"])
