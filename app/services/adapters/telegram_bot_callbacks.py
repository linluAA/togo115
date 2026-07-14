from __future__ import annotations

from typing import Any

import httpx

from app.db import add_log, db, utc_now
from app.services.adapters.media import TmdbAdapter
from app.services.adapters.pan115 import Pan115Adapter
from app.services.integration_state import get_setting
from app.services.subscription.delivery.executor import _deliver_resource_url
from app.services.tg_bot_magnet_search import (
    magnet_results_reply,
    magnet_results_reply_markup,
    pending_magnet_choices,
    pending_magnet_detail,
    pending_magnet_label,
    pending_magnet_pick,
    pending_magnet_target_path,
    search_magnets_for_tmdb,
)


class TelegramBotCallbackMixin:
    async def _handle_callback(self, client: httpx.AsyncClient, token: str, callback: dict[str, Any]) -> None:
        message = callback.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        callback_id = callback.get("id")
        data = str(callback.get("data") or "")
        config = self._config()
        if not self._chat_allowed(config, chat_id):
            await self._answer_callback(client, token, callback_id, "当前 Chat ID 未授权")
            return
        if data.startswith("preview:"):
            await self._handle_preview_callback(client, token, callback_id, chat_id, data)
            return
        if data.startswith("subscribe:"):
            await self._handle_subscribe_callback(client, token, callback_id, chat_id, message, data)
            return
        if data.startswith("magpick:"):
            await self._handle_magnet_pick_callback(client, token, callback_id, chat_id, message, data)
            return
        if data.startswith("magnet:"):
            await self._handle_magnet_callback(client, token, callback_id, chat_id, message, data)
            return
        if data == "cancel_preview":
            await self._answer_callback(client, token, callback_id, "已取消")
            await self._clear_message_buttons(client, token, message)
            return
        await self._answer_callback(client, token, callback_id, "未知操作")

    async def _handle_preview_callback(
        self,
        client: httpx.AsyncClient,
        token: str,
        callback_id: str | None,
        chat_id: int | str | None,
        data: str,
    ) -> None:
        try:
            await self._answer_callback(client, token, callback_id, "正在读取详情...")
            _, media_type, tmdb_id = data.split(":", 2)
            await self._send_subscription_preview(client, token, chat_id, media_type, int(tmdb_id))
        except Exception as exc:
            add_log("warning", "tg_bot", "TG Bot 发送订阅详情失败", {"data": data, "error": str(exc)})
            if chat_id:
                await self._send_bot_message(client, token, chat_id, f"详情获取失败：{str(exc)[:120]}")

    async def _handle_subscribe_callback(
        self,
        client: httpx.AsyncClient,
        token: str,
        callback_id: str | None,
        chat_id: int | str | None,
        message: dict[str, Any],
        data: str,
    ) -> None:
        try:
            await self._answer_callback(client, token, callback_id, "正在添加订阅...")
            _, media_type, tmdb_id = data.split(":", 2)
            detail = await TmdbAdapter().detail(media_type, int(tmdb_id))
            subscription = await self._create_subscription_from_detail(media_type, int(tmdb_id), detail)
            if chat_id:
                await self._send_bot_message(
                    client,
                    token,
                    chat_id,
                    f"已添加订阅：{subscription.get('title')}，ID {subscription.get('id')}\n已进入后台搜索，找到资源后会按当前投递方式处理。",
                )
            await self._clear_message_buttons(client, token, message)
        except Exception as exc:
            add_log("warning", "tg_bot", "TG Bot 回调订阅失败", {"data": data, "error": str(exc)})
            if chat_id:
                await self._send_bot_message(client, token, chat_id, f"订阅失败：{str(exc)[:120]}")

    async def _handle_magnet_callback(
        self,
        client: httpx.AsyncClient,
        token: str,
        callback_id: str | None,
        chat_id: int | str | None,
        message: dict[str, Any],
        data: str,
    ) -> None:
        try:
            await self._answer_callback(client, token, callback_id, "正在搜索磁力...")
            _, media_type, tmdb_id = data.split(":", 2)
            await self._edit_bot_message_text(client, token, message, "已选择，正在搜索磁力，请稍等...")
            detail, results = await search_magnets_for_tmdb(media_type, int(tmdb_id))
            if chat_id:
                reply_markup = magnet_results_reply_markup(detail, results) if results else None
                await self._send_bot_message(client, token, chat_id, magnet_results_reply(detail, results), reply_markup=reply_markup)
        except Exception as exc:
            add_log("warning", "tg_bot", "TG Bot 磁力搜索回调失败", {"data": data, "error": str(exc)})
            if chat_id:
                await self._send_bot_message(client, token, chat_id, f"磁力搜索失败：{str(exc)[:120]}")


    async def _handle_magnet_pick_callback(
        self,
        client: httpx.AsyncClient,
        token: str,
        callback_id: str | None,
        chat_id: int | str | None,
        message: dict[str, Any],
        data: str,
    ) -> None:
        try:
            _, pick_token, index_text = data.split(":", 2)
            index = int(index_text)
            result = pending_magnet_pick(pick_token, index)
            if not result:
                await self._answer_callback(client, token, callback_id, "选择已过期，请重新搜索")
                await self._clear_message_buttons(client, token, message)
                return
            await self._answer_callback(client, token, callback_id, "正在投递...")
            await self._clear_message_buttons(client, token, message)
            if chat_id:
                await self._send_bot_message(client, token, chat_id, f"已选择：{pending_magnet_label(pick_token, index)}\n正在按当前投递方式处理...")
            ok, error, delivered_index = await self._deliver_magnet_choices(pick_token, index)
            add_log(
                "info" if ok else "warning",
                "tg_bot",
                "TG Bot 磁力选择投递完成" if ok else "TG Bot 磁力选择投递失败",
                {"url": result.url, "source": result.source, "error": error, "selected_index": index, "delivered_index": delivered_index},
            )
            if chat_id:
                if ok and delivered_index != index:
                    text = f"所选磁力投递失败，已自动改投第 {delivered_index + 1} 个候选并成功。"
                else:
                    text = "投递成功" if ok else f"投递失败：{error or '未知错误'}"
                await self._send_bot_message(client, token, chat_id, text)
        except Exception as exc:
            add_log("warning", "tg_bot", "TG Bot 磁力选择回调失败", {"data": data, "error": str(exc)})
            if chat_id:
                await self._send_bot_message(client, token, chat_id, f"投递失败：{str(exc)[:120]}")

    async def _deliver_magnet_choices(self, token: str, start_index: int) -> tuple[bool, str, int | None]:
        last_error = ""
        target_path = pending_magnet_target_path(token)
        for index, result in pending_magnet_choices(token, start_index):
            ok, error = await self._deliver_magnet_pick(result.url, target_path, token=token)
            if ok:
                return True, "", index
            last_error = error
            add_log(
                "warning",
                "tg_bot",
                "TG Bot 磁力候选投递失败，继续尝试下一候选",
                {"index": index, "url": result.url, "source": result.source, "error": error},
            )
        return False, last_error or "全部候选投递失败", None

    async def _deliver_magnet_pick(self, url: str, target_path: str | None = None, token: str | None = None) -> tuple[bool, str]:
        resource_id = self._save_magnet_pick_as_resource(url, token)
        if resource_id:
            from app.services.subscription import deliver_resource

            ok = await deliver_resource(resource_id)
            return ok, "" if ok else "资源投递失败"
        delivery = get_setting("delivery", {"mode": "115"})
        delivery_mode = str(delivery.get("mode") or "115")
        resource = {"url": url, "target_path": target_path}
        return await _deliver_resource_url(resource, delivery_mode, Pan115Adapter, self.__class__)

    def _save_magnet_pick_as_resource(self, url: str, token: str | None) -> int | None:
        detail = pending_magnet_detail(token or "")
        tmdb_id = detail.get("id")
        media_type = detail.get("media_type")
        if not tmdb_id or media_type not in ("tv", "movie"):
            return None
        title = detail.get("name") or detail.get("title") or "TG Bot 磁力资源"
        now = utc_now()
        with db() as conn:
            row = conn.execute(
                """
                SELECT id FROM subscriptions
                WHERE status = 'active' AND tmdb_id = ? AND media_type = ?
                ORDER BY id DESC LIMIT 1
                """,
                (tmdb_id, media_type),
            ).fetchone()
            if not row:
                return None
            cursor = conn.execute(
                """
                INSERT INTO resources (subscription_id, source, title, url, message_id, status, created_at, updated_at)
                VALUES (?, 'tg_bot:magnet', ?, ?, NULL, 'pending', ?, ?)
                """,
                (int(row["id"]), str(title), url, now, now),
            )
            return int(cursor.lastrowid)

    async def _create_subscription_from_detail(self, media_type: str, tmdb_id: int, detail: dict[str, Any]) -> dict:
        from app.schemas import SubscriptionCreate
        from app.services.subscription import create_subscription

        title = detail.get("name") or detail.get("title") or "未命名"
        release_year_text = str(detail.get("first_air_date") or detail.get("release_date") or "")[:4]
        release_year = int(release_year_text) if release_year_text.isdigit() else None
        poster = f"https://image.tmdb.org/t/p/w500{detail.get('poster_path')}" if detail.get("poster_path") else None
        return await create_subscription(
            SubscriptionCreate(
                title=title,
                media_type=media_type,
                tmdb_id=tmdb_id,
                poster_url=poster,
                overview=detail.get("overview") or "",
                release_year=release_year,
                tmdb_total_count=detail.get("number_of_episodes") or 0,
                keywords=[title],
            )
        )
