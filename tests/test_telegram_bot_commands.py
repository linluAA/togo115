from __future__ import annotations

import unittest

from app.services.adapters.telegram.bot.commands import TelegramBotCommandMixin


class BotCommandHarness(TelegramBotCommandMixin):
    async def _send_subscription_choices(self, chat_id: int | str, query: str, media_type: str = "multi") -> None:
        self.sent_choice = {"chat_id": chat_id, "query": query, "media_type": media_type}

    async def _send_magnet_search_choices(self, chat_id: int | str, query: str) -> None:
        self.sent_magnet_choice = {"chat_id": chat_id, "query": query}


class TelegramBotCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_parse_chinese_subscribe_command(self) -> None:
        bot = BotCommandHarness()
        reply = await bot._command_reply("订阅 斗罗大陆", 123)

        self.assertEqual(reply, "")
        self.assertEqual(bot.sent_choice, {"chat_id": 123, "query": "斗罗大陆", "media_type": "multi"})

    async def test_parse_chinese_tv_subscribe_command(self) -> None:
        bot = BotCommandHarness()
        reply = await bot._command_reply("订阅剧集 斗罗大陆", 123)

        self.assertEqual(reply, "")
        self.assertEqual(bot.sent_choice, {"chat_id": 123, "query": "斗罗大陆", "media_type": "tv"})

    async def test_parse_chinese_movie_subscribe_command(self) -> None:
        bot = BotCommandHarness()
        reply = await bot._command_reply("订阅电影 流浪地球", 123)

        self.assertEqual(reply, "")
        self.assertEqual(bot.sent_choice, {"chat_id": 123, "query": "流浪地球", "media_type": "movie"})

    async def test_parse_magnet_search_command(self) -> None:
        bot = BotCommandHarness()
        reply = await bot._command_reply("搜 斗罗大陆", 123)

        self.assertEqual(reply, "")
        self.assertEqual(bot.sent_magnet_choice, {"chat_id": 123, "query": "斗罗大陆"})

    async def test_help_reply_is_readable_chinese(self) -> None:
        bot = BotCommandHarness()
        reply = await bot._command_reply("/help", 123)

        self.assertIn("可用命令", reply)
        self.assertIn("取消订阅", reply)
        self.assertIn("搜 片名", reply)

    def test_subscription_list_reply_formats_tv_progress(self) -> None:
        bot = BotCommandHarness()

        reply = bot._subscription_list_reply(
            [{"id": 1, "title": "南部档案", "media_type": "tv", "status": "active", "emby_count": 20, "tmdb_total_count": 30}]
        )

        self.assertIn("1. 南部档案 (剧集 20/30集)", reply)
