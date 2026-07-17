from __future__ import annotations

from typing import Any

import httpx

from app.services.http_client import shared_async_client

from app.db import add_log, json_dumps
from app.services.adapters.media import TmdbAdapter
from app.services.integration_state import get_setting, module_proxy
from app.services.magnet import tmdb_search_choices


class TelegramBotMessageMixin:
    async def _send_bot_message(
        self,
        client: httpx.AsyncClient,
        token: str,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text[:3900]}
        if reply_markup:
            data["reply_markup"] = json_dumps(reply_markup)
        res = await client.post(self._api_url(token, "sendMessage"), data=data)
        if res.status_code >= 400:
            add_log("warning", "tg_bot", "TG Bot \u56de\u590d\u6d88\u606f\u5931\u8d25", {"status": res.status_code, "body": res.text[:240]})

    async def _send_subscription_choices(self, chat_id: int | str, query: str, media_type: str = "multi") -> None:
        config = self._config()
        token = str(config.get("bot_token") or "").strip()
        if not token:
            return
        results = await TmdbAdapter().search(query, media_type)
        proxy = module_proxy("telegram")
        async with shared_async_client(proxy=proxy or None, timeout=25, follow_redirects=True) as client:
            if not results:
                await self._send_bot_message(client, token, chat_id, f"\u6ca1\u6709\u641c\u7d22\u5230\uff1a{query}")
                return
            buttons = []
            if media_type == "movie":
                choice_label = "\u7535\u5f71"
            elif media_type == "tv":
                choice_label = "\u5267\u96c6"
            else:
                choice_label = "\u5267\u96c6\u6216\u7535\u5f71"
            lines = [f"\u641c\u7d22\u5230 {min(len(results), 8)} \u4e2a\u7ed3\u679c\uff0c\u8bf7\u9009\u62e9{choice_label}\u67e5\u770b\u8be6\u60c5\uff1a"]
            for index, item in enumerate(results[:8], start=1):
                item_media_type = item.get("media_type") or ("movie" if media_type == "movie" else "tv")
                media_label = "\u7535\u5f71" if item_media_type == "movie" else "\u5267\u96c6"
                title = item.get("name") or item.get("title") or "\u672a\u547d\u540d"
                year = str(item.get("first_air_date") or item.get("release_date") or "")[:4] or "\u672a\u77e5\u5e74\u4efd"
                lines.append(f"{index}. [{media_label}] {title} ({year})")
                buttons.append([{"text": f"{index}. {media_label} - {title[:24]}", "callback_data": f"preview:{item_media_type}:{item.get('id')}"}])
            reply_markup = {"inline_keyboard": buttons}
            res = await client.post(
                self._api_url(token, "sendMessage"),
                data={"chat_id": chat_id, "text": "\n".join(lines)[:3900], "reply_markup": json_dumps(reply_markup)},
            )
            if res.status_code >= 400:
                add_log("warning", "tg_bot", "TG Bot \u53d1\u9001\u8ba2\u9605\u641c\u7d22\u7ed3\u679c\u5931\u8d25", {"status": res.status_code, "body": res.text[:240]})

    async def _send_magnet_search_choices(self, chat_id: int | str, query: str) -> None:
        config = self._config()
        token = str(config.get("bot_token") or "").strip()
        if not token:
            return
        results = await tmdb_search_choices(query)
        proxy = module_proxy("telegram")
        async with shared_async_client(proxy=proxy or None, timeout=25, follow_redirects=True) as client:
            if not results:
                await self._send_bot_message(client, token, chat_id, f"\u6ca1\u6709\u641c\u7d22\u5230\uff1a{query}")
                return
            lines = [f"\u641c\u7d22\u5230 {min(len(results), 8)} \u4e2a\u7ed3\u679c\uff0c\u8bf7\u9009\u62e9\u8981\u641c\u7d22\u78c1\u529b\u7684\u5267\u96c6\u6216\u7535\u5f71\uff1a"]
            buttons = []
            for index, item in enumerate(results[:8], start=1):
                media_type = item.get("media_type") or ("tv" if item.get("name") else "movie")
                media_label = "\u7535\u5f71" if media_type == "movie" else "\u5267\u96c6"
                title = item.get("name") or item.get("title") or "\u672a\u547d\u540d"
                year = str(item.get("first_air_date") or item.get("release_date") or "")[:4] or "\u672a\u77e5\u5e74\u4efd"
                lines.append(f"{index}. [{media_label}] {title} ({year})")
                buttons.append([{"text": f"{index}. {media_label} - {title[:24]}", "callback_data": f"magnet:{media_type}:{item.get('id')}"}])
            res = await client.post(
                self._api_url(token, "sendMessage"),
                data={"chat_id": chat_id, "text": "\n".join(lines)[:3900], "reply_markup": json_dumps({"inline_keyboard": buttons})},
            )
            if res.status_code >= 400:
                add_log("warning", "tg_bot", "TG Bot \u53d1\u9001\u78c1\u529b\u641c\u7d22\u9009\u62e9\u5931\u8d25", {"status": res.status_code, "body": res.text[:240]})

    async def _send_subscription_preview(self, client: httpx.AsyncClient, token: str, chat_id: int | str | None, media_type: str, tmdb_id: int) -> None:
        if not chat_id:
            return
        detail = await TmdbAdapter().detail(media_type, tmdb_id)
        title = detail.get("name") or detail.get("title") or "\u672a\u547d\u540d"
        year = str(detail.get("first_air_date") or detail.get("release_date") or "")[:4] or "\u672a\u77e5\u5e74\u4efd"
        total = detail.get("number_of_episodes")
        overview = detail.get("overview") or "\u6682\u65e0\u7b80\u4ecb"
        facts = f"{year}" + (f" · {total} \u96c6" if total else "")
        caption = f"{title}\n{facts}\n\n{overview[:520]}"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "\u786e\u8ba4\u8ba2\u9605", "callback_data": f"subscribe:{media_type}:{tmdb_id}"},
                {"text": "\u53d6\u6d88", "callback_data": "cancel_preview"},
            ]]
        }
        poster_path = detail.get("poster_path")
        if poster_path:
            res = await client.post(
                self._api_url(token, "sendPhoto"),
                data={
                    "chat_id": chat_id,
                    "photo": f"https://image.tmdb.org/t/p/w500{poster_path}",
                    "caption": caption[:1024],
                    "reply_markup": json_dumps(reply_markup),
                },
            )
        else:
            res = await client.post(
                self._api_url(token, "sendMessage"),
                data={"chat_id": chat_id, "text": caption[:3900], "reply_markup": json_dumps(reply_markup)},
            )
        if res.status_code >= 400:
            add_log("warning", "tg_bot", "TG Bot \u53d1\u9001\u8ba2\u9605\u8be6\u60c5\u5931\u8d25", {"status": res.status_code, "body": res.text[:240]})

    async def _answer_callback(self, client: httpx.AsyncClient, token: str, callback_id: str | None, text: str) -> None:
        if not callback_id:
            return
        await client.post(self._api_url(token, "answerCallbackQuery"), data={"callback_query_id": callback_id, "text": text[:180]})

    async def _clear_message_buttons(self, client: httpx.AsyncClient, token: str, message: dict[str, Any]) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        if not chat_id or not message_id:
            return
        res = await client.post(
            self._api_url(token, "editMessageReplyMarkup"),
            data={"chat_id": chat_id, "message_id": message_id, "reply_markup": json_dumps({"inline_keyboard": []})},
        )
        if res.status_code >= 400:
            add_log("debug", "tg_bot", "TG Bot \u6e05\u9664\u8be6\u60c5\u6309\u94ae\u5931\u8d25", {"status": res.status_code, "body": res.text[:240]})

    async def _edit_bot_message_text(
        self,
        client: httpx.AsyncClient,
        token: str,
        message: dict[str, Any],
        text: str,
    ) -> bool:
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        if not chat_id or not message_id:
            return False
        res = await client.post(
            self._api_url(token, "editMessageText"),
            data={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text[:3900],
                "reply_markup": json_dumps({"inline_keyboard": []}),
            },
        )
        if res.status_code < 400:
            return True
        add_log("debug", "tg_bot", "TG Bot 编辑消息失败", {"status": res.status_code, "body": res.text[:240]})
        await self._clear_message_buttons(client, token, message)
        return False

    async def forward_to_bot(self, link: str) -> bool:
        config = get_setting("tg_bot")
        bot_username = config.get("bot_username")
        if not bot_username:
            add_log("warning", "tg_bot", "TG Bot \u5c1a\u672a\u914d\u7f6e\uff0c\u65e0\u6cd5\u8f6c\u53d1\u94fe\u63a5", {"link": link})
            return False
        from app.services.adapters.telegram import TelegramClientAdapter

        tg = TelegramClientAdapter()
        if not await tg.is_authorized():
            return False
        client = await tg.client()
        await client.send_message(bot_username, link)
        add_log("info", "tg_bot", "\u5df2\u901a\u8fc7\u4e2a\u4eba TG \u8d26\u53f7\u53d1\u9001\u94fe\u63a5\u5230\u673a\u5668\u4eba", {"bot": bot_username})
        return True
