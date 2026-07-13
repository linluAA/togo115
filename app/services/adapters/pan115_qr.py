from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.services.adapters.pan115_state import add_log, get_flow, get_setting, save_flow, save_setting


class Pan115QrMixin:
    def _cookie_from_login(self, payload: dict[str, Any], client: httpx.AsyncClient) -> str:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        cookie_value = data.get("cookie") or data.get("cookies") or payload.get("cookie") or payload.get("cookies")
        parts: list[str] = []
        if isinstance(cookie_value, str):
            parts.extend(part.strip() for part in cookie_value.split(";") if part.strip())
        elif isinstance(cookie_value, dict):
            for key, value in cookie_value.items():
                if isinstance(value, dict):
                    value = value.get("value")
                if value is not None and value != "":
                    parts.append(f"{key}={value}")
        elif isinstance(cookie_value, list):
            for item in cookie_value:
                if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
                    parts.append(f"{item['name']}={item['value']}")
        for item in client.cookies.jar:
            pair = f"{item.name}={item.value}"
            if pair not in parts:
                parts.append(pair)
        return "; ".join(parts)

    async def qr_login_start(self, channel: str = "web") -> dict[str, Any]:
        async with self._client() as client:
            res = await client.get(self.QR_TOKEN_URL)
            res.raise_for_status()
            raw = res.json()
            data = raw.get("data", raw)
        uid = data.get("uid")
        qrcode_value = data.get("qrcode")
        token_time = data.get("time")
        sign = data.get("sign")
        if not uid or not token_time or not sign:
            raise RuntimeError(f"115 扫码 token 获取失败：{str(raw)[:240]}")
        qr_url = (
            f"/api/qr?data={quote(str(qrcode_value), safe='')}"
            if qrcode_value
            else f"/api/115/qrcode-image?uid={uid}&channel={channel}"
        )
        save_flow("115_qr", {"uid": uid, "time": token_time, "sign": sign, "qrcode": qrcode_value, "qr_url": qr_url, "status": "waiting", "channel": channel})
        add_log("info", "115", "115 扫码登录已创建", {"channel": channel})
        return {"qr_url": qr_url, "status": "waiting", "channel": channel}

    async def qrcode_image(self, uid: str, channel: str = "web") -> tuple[bytes, str]:
        tried: list[str] = []
        channels = list(dict.fromkeys([channel, "mac", "web"]))
        async with self._client() as client:
            for item in channels:
                tried.append(item)
                url = self.QR_IMAGE_URL.format(channel=item)
                try:
                    res = await client.get(url, params={"uid": uid})
                    content_type = res.headers.get("content-type", "image/png")
                    if res.status_code == 200 and content_type.startswith("image/") and res.content:
                        return res.content, content_type
                    add_log("warning", "115", "115 二维码图片获取失败，尝试下一个渠道", {"channel": item, "status": res.status_code, "body": res.text[:120]})
                except Exception as exc:
                    add_log("warning", "115", "115 二维码图片请求异常，尝试下一个渠道", {"channel": item, "error": str(exc)})
        raise RuntimeError(f"二维码图片获取失败，已尝试渠道：{', '.join(tried)}")

    async def qr_login_status(self) -> dict[str, Any]:
        flow = get_flow("115_qr")
        config = get_setting("115")
        if not flow and config.get("cookie"):
            return {"status": "authorized", "cookie": config.get("cookie")}
        if not flow:
            return {"status": "not_started"}
        params = {"uid": flow["uid"], "time": flow.get("time"), "sign": flow["sign"]}
        async with self._client() as client:
            res = await client.get(self.QR_STATUS_URL, params=params)
            res.raise_for_status()
            data = res.json().get("data", res.json())
            status = str(data.get("status") or data.get("code") or "")
            if status in ("2", "confirmed", "login"):
                channel = flow.get("channel") or "web"
                login_url = self.QR_LOGIN_URL.format(channel=channel)
                login = await client.post(login_url, data={"account": flow["uid"], "app": channel})
                login.raise_for_status()
                login_payload = login.json()
                cookie = self._cookie_from_login(login_payload, client)
                if not cookie:
                    add_log("error", "115", "115 扫码登录未返回 Cookie", {"response": str(login_payload)[:500]})
                    save_flow("115_qr", {**flow, "status": "cookie_missing"})
                    return {"status": "cookie_missing", "detail": "115 登录接口未返回 Cookie"}
                config["cookie"] = cookie
                config["qr_login"] = "已登录"
                save_setting("115", config)
                save_flow("115_qr", {**flow, "status": "authorized"})
                add_log("info", "115", "115 扫码登录成功，Cookie 已保存")
                return {"status": "authorized", "cookie": cookie}
        save_flow("115_qr", {**flow, "status": status or "waiting"})
        return {"status": status or "waiting", "qr_url": flow.get("qr_url")}

