from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.services.adapters.pan115_offline import Pan115OfflineMixin
from app.services.adapters.pan115_qr import Pan115QrMixin
from app.services.adapters.pan115_state import add_log, get_setting, module_proxy


SHARE_AVAILABLE = "available"
SHARE_UNAVAILABLE = "unavailable"
SHARE_UNKNOWN = "unknown"

PAN115_URL_RE = re.compile(r'(?:https?://)?(?:www\.)?115(?:cdn)?\.com/s/[A-Za-z0-9_-]+(?:\?(?:password|pwd|receive_code)=[A-Za-z0-9]{2,12})?', re.I)


def normalize_115_share_link(link: str) -> str:
    match = PAN115_URL_RE.search(str(link or "").strip())
    if not match:
        return ""
    value = match.group(0)
    if value.casefold().startswith(("115.com/", "115cdn.com/", "www.115.com/", "www.115cdn.com/")):
        value = f"https://{value}"
    return value


def parse_115_share_link(link: str) -> tuple[str, str | None]:
    clean_link = normalize_115_share_link(link)
    if not clean_link:
        return "", None
    parsed = urlparse(clean_link)
    share_code = parsed.path.rstrip("/").split("/")[-1]
    receive_code = None
    match = re.search(r"(?i)(?:^|[?&])(?:password|pwd|receive_code)=([A-Za-z0-9]{2,12})", parsed.query)
    if match:
        receive_code = match.group(1)
    return share_code, receive_code



class Pan115Adapter(Pan115QrMixin, Pan115OfflineMixin):
    QR_TOKEN_URL = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
    QR_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
    QR_IMAGE_URL = "https://qrcodeapi.115.com/api/1.0/{channel}/1.0/qrcode"
    QR_LOGIN_URL = "https://passportapi.115.com/app/1.0/{channel}/1.0/login/qrcode/"
    SHARE_RECEIVE_URL = "https://webapi.115.com/share/receive"
    FILE_ADD_URL = "https://webapi.115.com/files/add"
    FILES_LIST_URL = "https://webapi.115.com/files"
    SHARE_SNAP_URL = "https://webapi.115.com/share/snap"
    USER_NAV_URL = "https://my.115.com/?ct=ajax&ac=nav"
    OFFLINE_SPACE_URL = "https://115.com/?ct=offline&ac=space"
    OFFLINE_ADD_TASK_URL = "https://115.com/web/lixian/?ct=lixian&ac=add_task_url"
    OFFLINE_REFERER = "https://115.com/?ct=offline&ac=tasklist"

    def _client(self) -> httpx.AsyncClient:
        proxy = module_proxy("pan115")
        return httpx.AsyncClient(proxy=proxy or None, timeout=25, follow_redirects=True)

    def _folder_item(self, item: dict[str, Any]) -> dict[str, str] | None:
        cid = item.get("cid") or item.get("file_id") or item.get("fid") or item.get("id")
        name = item.get("n") or item.get("name") or item.get("file_name") or item.get("title")
        is_dir = item.get("is_dir")
        if is_dir is None:
            is_dir = item.get("fc") == "0" or item.get("ico") == "folder" or bool(item.get("cid") and not item.get("fid"))
        if not is_dir or cid is None or not name:
            return None
        return {"id": str(cid), "name": str(name)}

    def _transfer_ok(self, payload: dict[str, Any]) -> bool:
        if payload.get("state") or payload.get("errno") == 0 or payload.get("errcode") == 0 or payload.get("code") == 0:
            return True
        message = str(
            payload.get("message")
            or payload.get("msg")
            or payload.get("error")
            or payload.get("errno_msg")
            or payload.get("err_msg")
            or ""
        )
        return "已接收" in message or "重复接收" in message or "无需重复" in message

    def _share_available_payload(self, payload: dict[str, Any]) -> bool:
        if payload.get("state") is True or payload.get("errno") == 0 or payload.get("errcode") == 0 or payload.get("code") == 0:
            return True
        message = str(
            payload.get("message")
            or payload.get("msg")
            or payload.get("error")
            or payload.get("errno_msg")
            or payload.get("err_msg")
            or ""
        ).casefold()
        unavailable_words = (
            "不存在",
            "取消",
            "过期",
            "失效",
            "提取码",
            "访问码",
            "错误",
            "invalid",
            "expired",
            "not found",
            "not exist",
            "share not found",
        )
        return not any(word in message for word in unavailable_words)

    async def share_available(self, link: str) -> bool:
        return await self.share_availability(link) == SHARE_AVAILABLE

    async def share_availability(self, link: str) -> str:
        clean_link = normalize_115_share_link(link)
        share_code, receive_code = parse_115_share_link(clean_link)
        if not clean_link or not share_code:
            add_log("info", "115", "115 分享链接格式无效", {"link": str(link or "")[:240]})
            return SHARE_UNAVAILABLE
        config = get_setting("115")
        if not config.get("cookie"):
            add_log("debug", "115", "115 Cookie 尚未配置，跳过分享有效性检测", {"link": clean_link})
            return SHARE_AVAILABLE
        headers = {"Referer": clean_link, "Cookie": config["cookie"]}
        params = {
            "share_code": share_code,
            "receive_code": receive_code or "",
            "offset": 0,
            "limit": 1,
        }
        try:
            async with self._client() as client:
                res = await client.get(self.SHARE_SNAP_URL, params=params, headers=headers)
            if res.status_code in {404, 410}:
                add_log("info", "115", "115 分享链接不可用", {"link": clean_link, "status": res.status_code})
                return SHARE_UNAVAILABLE
            if res.status_code >= 500:
                add_log("warning", "115", "115 分享有效性检测服务异常，已标记待复检", {"status": res.status_code, "link": clean_link})
                return SHARE_UNKNOWN
            if res.status_code >= 400:
                add_log("warning", "115", "115 分享有效性检测请求失败，已标记待复检", {"status": res.status_code, "link": clean_link})
                return SHARE_UNKNOWN
            payload = res.json()
            ok = self._share_available_payload(payload)
            if not ok:
                add_log("info", "115", "115 分享链接不可用", {"link": clean_link, "response": payload})
                return SHARE_UNAVAILABLE
            return SHARE_AVAILABLE
        except (UnicodeEncodeError, httpx.InvalidURL) as exc:
            add_log("warning", "115", "115 分享链接格式异常，已判定不可用", {"link": str(link or "")[:240], "clean_link": clean_link, "error": repr(exc)})
            return SHARE_UNAVAILABLE
        except Exception as exc:
            add_log("warning", "115", "115 分享有效性检测异常，已标记待复检", {"link": clean_link, "error": str(exc), "error_type": type(exc).__name__, "error_repr": repr(exc)})
            return SHARE_UNKNOWN

    async def list_folders(self, cid: str = "0") -> dict[str, Any]:
        config = get_setting("115")
        cookie = config.get("cookie")
        if not cookie:
            raise RuntimeError("115 Cookie 尚未配置，请先扫码登录")
        params = {
            "aid": 1,
            "cid": cid or "0",
            "offset": 0,
            "limit": 200,
            "show_dir": 1,
            "qid": 0,
            "type": "",
            "format": "json",
            "r_all": 1,
            "o": "file_name",
            "suffix": "",
            "asc": 1,
            "cur": 1,
            "natsort": 1,
        }
        async with self._client() as client:
            res = await client.get(self.FILES_LIST_URL, params=params, headers={"Cookie": cookie})
            res.raise_for_status()
            raw = res.json()
        data = raw.get("data", raw)
        items = data.get("list", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise RuntimeError(f"115 目录列表返回异常：{str(raw)[:240]}")
        folders = [folder for item in items if isinstance(item, dict) and (folder := self._folder_item(item))]
        return {"cid": str(cid or "0"), "folders": folders}

    async def ensure_folder(self, target_path: str | None) -> str:
        if not target_path or target_path == "/":
            return "0"
        config = get_setting("115")
        cookie = config.get("cookie")
        if not cookie:
            return "0"
        parent_id = "0"
        async with self._client() as client:
            for name in [x for x in target_path.strip("/").split("/") if x]:
                res = await client.post(self.FILE_ADD_URL, data={"pid": parent_id, "cname": name}, headers={"Cookie": cookie})
                if res.status_code == 200:
                    data = res.json()
                    parent_id = str(data.get("cid") or data.get("file_id") or data.get("data", {}).get("cid") or parent_id)
        return parent_id

    async def transfer(self, link: str, target_path: str | None) -> bool:
        config = get_setting("115")
        cookie = config.get("cookie")
        if not cookie:
            add_log("warning", "115", "115 Cookie 尚未配置，无法自动转存", {"link": link})
            return False
        share_code, receive_code = parse_115_share_link(link)
        cid = str(config.get("target_cid") or "")
        if not cid:
            cid = await self.ensure_folder(target_path or config.get("target_path"))
        payload = {"share_code": share_code, "receive_code": receive_code or "", "cid": cid}
        async with self._client() as client:
            res = await client.post(self.SHARE_RECEIVE_URL, data=payload, headers={"Cookie": cookie, "Referer": link})
        if res.status_code >= 400:
            add_log("error", "115", "115 转存请求失败", {"status": res.status_code, "body": res.text[:300]})
            return False
        data = res.json()
        ok = self._transfer_ok(data)
        add_log("info" if ok else "warning", "115", "115 转存完成" if ok else "115 转存未成功", {"link": link, "response": data})
        return ok




__all__ = ["PAN115_URL_RE", "Pan115Adapter", "SHARE_AVAILABLE", "SHARE_UNAVAILABLE", "SHARE_UNKNOWN", "normalize_115_share_link", "parse_115_share_link"]
