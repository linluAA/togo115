from __future__ import annotations

from typing import Any

import httpx

from app.services.adapters.pan115_state import add_log, get_setting


class Pan115OfflineMixin:
    def _offline_headers(self, cookie: str) -> dict[str, str]:
        return {
            "Cookie": cookie,
            "Origin": "https://115.com",
            "Referer": self.OFFLINE_REFERER,
        }

    def _offline_ok(self, payload: dict[str, Any]) -> bool:
        return bool(
            payload.get("state")
            or payload.get("errno") == 0
            or payload.get("errcode") == 0
            or payload.get("code") == 0
        )

    async def _offline_user_id(self, client: httpx.AsyncClient, headers: dict[str, str]) -> str:
        res = await client.get(self.USER_NAV_URL, headers=headers)
        res.raise_for_status()
        raw = res.json()
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        return str(data.get("user_id") or data.get("uid") or raw.get("user_id") or raw.get("uid") or "")

    async def _offline_sign(self, client: httpx.AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
        res = await client.get(self.OFFLINE_SPACE_URL, headers=headers)
        res.raise_for_status()
        raw = res.json()
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        sign = data.get("sign") or raw.get("sign")
        sign_time = data.get("time") or raw.get("time")
        if not sign or not sign_time:
            raise RuntimeError(f"115 离线下载签名获取失败：{str(raw)[:240]}")
        return str(sign), str(sign_time)

    async def offline_download(self, link: str, target_path: str | None) -> bool:
        config = get_setting("115")
        cookie = config.get("cookie")
        if not cookie:
            add_log("warning", "115", "115 Cookie 尚未配置，无法添加离线下载任务", {"link": link})
            return False
        cid = str(config.get("target_cid") or "")
        if not cid:
            cid = await self.ensure_folder(target_path or config.get("target_path"))
        headers = self._offline_headers(cookie)
        async with self._client() as client:
            uid = await self._offline_user_id(client, headers)
            sign, sign_time = await self._offline_sign(client, headers)
            payload = {
                "url": link,
                "uid": uid,
                "sign": sign,
                "time": sign_time,
                "wp_path_id": cid or "0",
                "savepath": "",
            }
            res = await client.post(self.OFFLINE_ADD_TASK_URL, data=payload, headers=headers)
        if res.status_code >= 400:
            add_log("error", "115", "115 离线下载请求失败", {"status": res.status_code, "body": res.text[:300], "link": link})
            return False
        data = res.json()
        ok = self._offline_ok(data)
        add_log(
            "info" if ok else "warning",
            "115",
            "115 离线下载任务已添加" if ok else "115 离线下载任务添加失败",
            {"link": link, "target_cid": cid or "0", "response": data},
        )
        return ok
