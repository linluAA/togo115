from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from telethon.errors import SessionPasswordNeededError

from app.db import add_log, utc_now
from app.services.integration_state import get_flow, save_flow


class _TelegramLoginMixin:
    async def qr_login_start(self) -> dict[str, Any]:
        client = await self.client()
        qr = await client.qr_login()
        qr_url = f"/api/qr?data={quote(str(qr.url), safe='')}"
        save_flow("telegram_login", self._qr_flow_payload(qr.url, qr_url, "waiting"))
        asyncio.create_task(self._wait_qr_login(qr, qr_url))
        return {"url": qr.url, "qr_url": qr_url, "status": "waiting"}

    async def _wait_qr_login(self, qr, qr_url: str) -> None:
        try:
            await qr.wait(timeout=120)
            save_flow("telegram_login", self._qr_flow_payload(qr.url, qr_url, "authorized"))
            add_log("info", "telegram", "Telegram 扫码登录成功")
        except SessionPasswordNeededError:
            save_flow("telegram_login", self._qr_flow_payload(qr.url, qr_url, "password_required"))
            add_log("warning", "telegram", "Telegram 需要两步验证密码")
        except Exception as exc:
            payload = self._qr_flow_payload(qr.url, qr_url, "failed")
            save_flow("telegram_login", {**payload, "error": str(exc)})
            add_log("warning", "telegram", "Telegram 扫码登录等待结束", {"error": str(exc)})

    def _qr_flow_payload(self, url: str, qr_url: str, status: str) -> dict[str, Any]:
        return {"method": "qr", "url": url, "qr_url": qr_url, "status": status, "started_at": utc_now()}

    async def send_login_code(self, phone: str) -> dict[str, Any]:
        client = await self.client()
        sent = await client.send_code_request(phone)
        save_flow(
            "telegram_login",
            {
                "method": "phone",
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
                "status": "code_sent",
                "started_at": utc_now(),
            },
        )
        add_log("info", "telegram", "Telegram 手机验证码已发送")
        return {"status": "code_sent"}

    async def sign_in_code(self, phone: str, code: str) -> dict[str, Any]:
        client = await self.client()
        flow = get_flow("telegram_login")
        phone_code_hash = flow.get("phone_code_hash")
        if not phone_code_hash or flow.get("phone") != phone:
            raise RuntimeError("请先发送 Telegram 手机验证码")
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            save_flow("telegram_login", {**flow, "status": "password_required"})
            add_log("warning", "telegram", "Telegram 手机验证码通过，需要两步验证密码")
            return {"status": "password_required"}
        save_flow("telegram_login", {**flow, "status": "authorized"})
        add_log("info", "telegram", "Telegram 手机验证码登录成功")
        return {"status": "authorized"}

    async def login_status(self) -> dict[str, Any]:
        flow = get_flow("telegram_login")
        authorized = await self.is_authorized()
        status = "authorized" if authorized else flow.get("status") or "not_authorized"
        if not authorized and status == "authorized":
            status = "not_authorized"
            save_flow("telegram_login", {**flow, "status": status})
        return {**flow, "authorized": authorized, "status": status}
