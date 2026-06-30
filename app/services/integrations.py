import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

from app.config import settings
from app.db import add_log, db, json_dumps, json_loads, utc_now

PAN115_URL_RE = re.compile(r"https?://(?:www\.)?115(?:cdn)?\.com/s/[A-Za-z0-9_-]+(?:\?[^\s\"'<>)]+)?", re.I)


def get_setting(key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json_loads(row["value"] if row else None, default or {})


def save_setting(key: str, value: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json_dumps(value), utc_now()),
        )


def get_flow(provider: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT payload FROM login_flows WHERE provider = ?", (provider,)).fetchone()
    return json_loads(row["payload"] if row else None, {})


def save_flow(provider: str, payload: dict[str, Any]) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO login_flows (provider, payload, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (provider, json_dumps(payload), now, now),
        )


def module_proxy(module: str) -> str | None:
    proxy = get_setting("proxy")
    modules = proxy.get("modules") or []
    if isinstance(modules, str):
        modules = [x.strip() for x in modules.split(",") if x.strip()]
    return proxy.get("url") if module in modules else None


@dataclass
class SearchResult:
    title: str
    url: str
    source: str
    message_id: str | None = None
    context: str = ""


def extract_115_links(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for match in PAN115_URL_RE.findall(text):
        link = match.rstrip("，。；,.;")
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def parse_115_share_link(link: str) -> tuple[str, str | None]:
    parsed = urlparse(link)
    share_code = parsed.path.rstrip("/").split("/")[-1]
    params = parse_qs(parsed.query)
    receive_code = params.get("password", params.get("pwd", params.get("receive_code", [None])))[0]
    return share_code, receive_code


class TelegramClientAdapter:
    _client: TelegramClient | None = None
    _listener_task: asyncio.Task | None = None
    _handler_registered: bool = False

    def _session_path(self) -> Path:
        return settings.data_dir / "telegram_user"

    def _config(self) -> dict[str, Any]:
        config = get_setting("telegram")
        if not config.get("api_id") or not config.get("api_hash"):
            raise RuntimeError("Telegram API ID/API HASH 尚未配置")
        return config

    async def client(self) -> TelegramClient:
        cls = type(self)
        if cls._client and cls._client.is_connected():
            return cls._client
        config = self._config()
        proxy = self._telethon_proxy(module_proxy("telegram"))
        cls._client = TelegramClient(str(self._session_path()), int(config["api_id"]), config["api_hash"], proxy=proxy)
        await cls._client.connect()
        return cls._client

    def _telethon_proxy(self, proxy_url: str | None):
        if not proxy_url:
            return None
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        if scheme.startswith("socks"):
            try:
                import socks
            except ImportError as exc:
                raise RuntimeError("使用 socks 代理需要安装 PySocks") from exc
            proxy_type = socks.SOCKS5 if scheme == "socks5" else socks.SOCKS4
            return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password)
        if scheme in ("http", "https"):
            return ("http", parsed.hostname, parsed.port, True, parsed.username, parsed.password)
        return None

    async def is_authorized(self) -> bool:
        try:
            client = await self.client()
            return await client.is_user_authorized()
        except Exception as exc:
            add_log("warning", "telegram", "Telegram 授权状态检查失败", {"error": str(exc)})
            return False

    async def qr_login_start(self) -> dict[str, Any]:
        client = await self.client()
        qr = await client.qr_login()
        qr_url = f"/api/qr?data={quote(str(qr.url), safe='')}"
        save_flow("telegram_login", {"method": "qr", "url": qr.url, "qr_url": qr_url, "status": "waiting", "started_at": utc_now()})
        async def waiter() -> None:
            try:
                await qr.wait(timeout=120)
                save_flow("telegram_login", {"method": "qr", "url": qr.url, "qr_url": qr_url, "status": "authorized", "started_at": utc_now()})
                add_log("info", "telegram", "Telegram 扫码登录成功")
            except SessionPasswordNeededError:
                add_log("warning", "telegram", "Telegram 需要两步验证密码")
                save_flow("telegram_login", {"method": "qr", "url": qr.url, "qr_url": qr_url, "status": "password_required", "started_at": utc_now()})
            except Exception as exc:
                save_flow("telegram_login", {"method": "qr", "url": qr.url, "qr_url": qr_url, "status": "failed", "error": str(exc), "started_at": utc_now()})
                add_log("warning", "telegram", "Telegram 扫码登录等待结束", {"error": str(exc)})
        asyncio.create_task(waiter())
        return {"url": qr.url, "qr_url": qr_url, "status": "waiting"}

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

    async def sign_in_password(self, password: str) -> bool:
        client = await self.client()
        await client.sign_in(password=password)
        flow = get_flow("telegram_login")
        save_flow("telegram_login", {**flow, "status": "authorized"})
        add_log("info", "telegram", "Telegram 两步验证登录成功")
        return True

    async def login_status(self) -> dict[str, Any]:
        flow = get_flow("telegram_login")
        authorized = await self.is_authorized()
        status = "authorized" if authorized else flow.get("status") or "not_authorized"
        if not authorized and status == "authorized":
            status = "not_authorized"
            save_flow("telegram_login", {**flow, "status": status})
        return {**flow, "authorized": authorized, "status": status}

    async def dialogs(self) -> list[dict[str, Any]]:
        client = await self.client()
        if not await client.is_user_authorized():
            return []
        items: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not (getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False)):
                continue
            identifier = getattr(entity, "username", None) or str(entity.id)
            items.append(
                {
                    "id": str(entity.id),
                    "title": dialog.name,
                    "username": getattr(entity, "username", None),
                    "source": identifier,
                    "type": "频道" if getattr(entity, "broadcast", False) else "群组",
                }
            )
        return items

    async def search_history(self, title: str, keywords: list[str]) -> list[SearchResult]:
        try:
            client = await self.client()
        except Exception as exc:
            add_log("warning", "telegram", "Telegram 尚未可用，历史搜索跳过", {"error": str(exc)})
            return []
        if not await client.is_user_authorized():
            add_log("warning", "telegram", "Telegram 尚未登录，历史搜索跳过")
            return []
        config = self._config()
        dialogs = [x.strip() for x in str(config.get("sources", "")).split(",") if x.strip()]
        if not dialogs:
            add_log("warning", "telegram", "未配置 Telegram 群组/频道 sources")
            return []
        clean_keywords = [item.strip() for item in keywords if item and item.strip() and item.strip() != title]
        queries = [title, *(f"{title} {keyword}" for keyword in clean_keywords)]
        results: list[SearchResult] = []
        for dialog in dialogs:
            for query in dict.fromkeys(queries):
                async for message in client.iter_messages(dialog, search=query, limit=int(config.get("history_limit") or 80)):
                    results.extend(await self._links_from_message(client, message, dialog))
        add_log("info", "telegram", "Telegram 历史搜索完成", {"title": title, "count": len(results)})
        return results

    async def _links_from_message(self, client: TelegramClient, message: Any, source: str) -> list[SearchResult]:
        message_text = message.raw_text or ""
        link_contexts: dict[str, str] = {link: message_text for link in extract_115_links(message_text)}
        if not link_contexts and getattr(message, "buttons", None):
            for link, button_text in await self._click_buttons_for_links(message):
                context = "\n".join(part for part in (message_text, button_text) if part)
                link_contexts.setdefault(link, context)
        return [
            SearchResult(
                title=(context or "Telegram 资源")[:120],
                url=link,
                source=str(source),
                message_id=str(message.id),
                context=context,
            )
            for link, context in link_contexts.items()
        ]

    async def _click_buttons_for_links(self, message: Any) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        for row_index, row in enumerate(message.buttons or []):
            for col_index, button in enumerate(row):
                label = getattr(button, "text", "") or ""
                if not any(word in label.lower() for word in ("115", "链接", "查看", "打开", "资源", "link")):
                    continue
                try:
                    response = await message.click(row_index, col_index)
                    text = getattr(response, "raw_text", None) or getattr(response, "message", None) or (response if isinstance(response, str) else None)
                    links.extend((link, text or label) for link in extract_115_links(text))
                except Exception as exc:
                    add_log("debug", "telegram", "点击 Telegram 消息按钮未取得链接", {"message_id": message.id, "button": label, "error": str(exc)})
        return links

    async def ensure_monitoring(self) -> None:
        if not await self.is_authorized():
            return
        cls = type(self)
        if cls._listener_task and not cls._listener_task.done():
            add_log("debug", "telegram", "Telegram 监控心跳正常")
            return
        client = await self.client()
        config = self._config()
        dialogs = [x.strip() for x in str(config.get("sources", "")).split(",") if x.strip()]
        if not dialogs:
            return

        if not cls._handler_registered:
            @client.on(events.NewMessage(chats=dialogs))
            async def handler(event) -> None:
                from app.services.subscription import attach_results_to_matching_subscriptions
                results = await self._links_from_message(client, event.message, str(event.chat_id))
                if results:
                    await attach_results_to_matching_subscriptions(results, event.message.raw_text or "")
            cls._handler_registered = True

        cls._listener_task = asyncio.create_task(client.run_until_disconnected())
        add_log("info", "telegram", "Telegram 实时监控已启动", {"sources": dialogs})


class Pan115Adapter:
    QR_TOKEN_URL = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
    QR_STATUS_URL = "https://qrcodeapi.115.com/get/status/"
    QR_IMAGE_URL = "https://qrcodeapi.115.com/api/1.0/{channel}/1.0/qrcode"
    QR_LOGIN_URL = "https://passportapi.115.com/app/1.0/{channel}/1.0/login/qrcode/"
    SHARE_RECEIVE_URL = "https://webapi.115.com/share/receive"
    FILE_ADD_URL = "https://webapi.115.com/files/add"
    FILES_LIST_URL = "https://webapi.115.com/files"

    def _client(self) -> httpx.AsyncClient:
        proxy = module_proxy("pan115")
        return httpx.AsyncClient(proxy=proxy or None, timeout=25, follow_redirects=True)

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

    def _folder_item(self, item: dict[str, Any]) -> dict[str, str] | None:
        cid = item.get("cid") or item.get("file_id") or item.get("fid") or item.get("id")
        name = item.get("n") or item.get("name") or item.get("file_name") or item.get("title")
        is_dir = item.get("is_dir")
        if is_dir is None:
            is_dir = item.get("fc") == "0" or item.get("ico") == "folder" or bool(item.get("cid") and not item.get("fid"))
        if not is_dir or cid is None or not name:
            return None
        return {"id": str(cid), "name": str(name)}

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
        ok = bool(data.get("state") or data.get("errno") == 0)
        add_log("info" if ok else "warning", "115", "115 转存完成" if ok else "115 转存未成功", {"link": link, "response": data})
        return ok


class TelegramBotAdapter:
    async def forward_to_bot(self, link: str) -> bool:
        config = get_setting("tg_bot")
        bot_username = config.get("bot_username")
        if not bot_username:
            add_log("warning", "tg_bot", "TG Bot 尚未配置，无法转发链接", {"link": link})
            return False
        tg = TelegramClientAdapter()
        if not await tg.is_authorized():
            return False
        client = await tg.client()
        await client.send_message(bot_username, link)
        add_log("info", "tg_bot", "已通过个人 TG 账号发送链接到机器人", {"bot": bot_username})
        return True


class TmdbAdapter:
    async def _client(self) -> httpx.AsyncClient:
        proxy = module_proxy("tmdb")
        return httpx.AsyncClient(proxy=proxy or None, timeout=20)

    def _api_key(self) -> str | None:
        return get_setting("tmdb").get("api_key")

    async def trending(self) -> dict[str, list[dict[str, Any]]]:
        api_key = self._api_key()
        if not api_key:
            return {"tv": [], "movie": []}
        async with await self._client() as client:
            tv = await client.get("https://api.themoviedb.org/3/trending/tv/week", params={"api_key": api_key, "language": "zh-CN"})
            movie = await client.get("https://api.themoviedb.org/3/trending/movie/week", params={"api_key": api_key, "language": "zh-CN"})
        tv.raise_for_status()
        movie.raise_for_status()
        return {"tv": tv.json().get("results", []), "movie": movie.json().get("results", [])}

    async def search(self, query: str, media_type: str = "multi") -> list[dict[str, Any]]:
        api_key = self._api_key()
        if not api_key or not query.strip():
            return []
        endpoint = "multi" if media_type not in ("tv", "movie") else media_type
        async with await self._client() as client:
            res = await client.get(
                f"https://api.themoviedb.org/3/search/{endpoint}",
                params={"api_key": api_key, "language": "zh-CN", "query": query, "include_adult": "false"},
            )
        res.raise_for_status()
        return [item for item in res.json().get("results", []) if item.get("media_type", endpoint) in ("tv", "movie")]

    async def detail(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        api_key = self._api_key()
        if not api_key:
            return {}
        async with await self._client() as client:
            res = await client.get(
                f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
                params={"api_key": api_key, "language": "zh-CN", "append_to_response": "credits,videos"},
            )
        res.raise_for_status()
        return res.json()


class EmbyAdapter:
    def _base_url(self, config: dict[str, Any]) -> str:
        return str(config.get("server_url", "")).rstrip("/")

    async def _get(self, client: httpx.AsyncClient, base_url: str, path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
        query = {"api_key": api_key, **(params or {})}
        res = await client.get(f"{base_url}{path}", params=query, headers={"X-Emby-Token": api_key})
        res.raise_for_status()
        return res.json()

    async def library_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return {"movies": [], "series": [], "episodes": []}
        proxy = module_proxy("emby")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=30, follow_redirects=True) as client:
            common_params = {
                "Recursive": "true",
                "Limit": "10000",
                "Fields": "ProviderIds,OriginalTitle,SortName,SeriesId,SeriesName,ParentId,IndexNumber,ParentIndexNumber",
            }
            movies_series = await self._get(
                client,
                base_url,
                "/Items",
                api_key,
                {**common_params, "IncludeItemTypes": "Movie,Series"},
            )
            episodes = await self._get(
                client,
                base_url,
                "/Items",
                api_key,
                {**common_params, "IncludeItemTypes": "Episode"},
            )
        items = movies_series.get("Items", [])
        return {
            "movies": [item for item in items if item.get("Type") == "Movie"],
            "series": [item for item in items if item.get("Type") == "Series"],
            "episodes": episodes.get("Items", []),
        }

    async def dashboard(self) -> dict[str, Any]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return {"media_count": 0, "libraries": [], "users": [], "history": []}
        proxy = module_proxy("emby")
        try:
            async with httpx.AsyncClient(proxy=proxy or None, timeout=20, follow_redirects=True) as client:
                counts = await self._get(client, base_url, "/Items/Counts", api_key)
                folders = await self._get(client, base_url, "/Library/VirtualFolders", api_key)
                users_raw = await self._get(client, base_url, "/Users", api_key)

                libraries = []
                for folder in folders:
                    item_id = folder.get("ItemId")
                    libraries.append(
                        {
                            "id": item_id,
                            "name": folder.get("Name") or "媒体库",
                            "collection_type": folder.get("CollectionType") or "",
                            "description": folder.get("CollectionType") or "",
                            "image_url": f"/api/emby/image/{item_id}" if item_id else "",
                        }
                    )

                users = [
                    {
                        "id": user.get("Id"),
                        "name": user.get("Name") or "用户",
                        "description": "已禁用" if user.get("Policy", {}).get("IsDisabled") else "正常",
                        "image_url": f"/api/emby/user-image/{user.get('Id')}" if user.get("Id") else "",
                    }
                    for user in users_raw
                ]

                history: list[dict[str, Any]] = []
                for user in users:
                    if not user.get("id"):
                        continue
                    history_params = {
                        "Recursive": "true",
                        "IsPlayed": "true",
                        "Filters": "IsPlayed",
                        "SortBy": "DatePlayed",
                        "SortOrder": "Descending",
                        "Limit": 12,
                        "IncludeItemTypes": "Movie,Episode",
                        "Fields": "DatePlayed,DateCreated,PrimaryImageAspectRatio,SeriesName,UserData",
                        "EnableUserData": "true",
                    }
                    played = await self._get(client, base_url, f"/Users/{user['id']}/Items", api_key, history_params)
                    for item in played.get("Items", []):
                        user_data = item.get("UserData", {})
                        played_at = user_data.get("LastPlayedDate") or item.get("DatePlayed") or item.get("DateCreated") or ""
                        image_id = item.get("SeriesId") or item.get("Id")
                        history.append(
                            {
                                "id": item.get("Id"),
                                "name": item.get("Name") or "媒体",
                                "title": item.get("SeriesName") or item.get("Name") or "媒体",
                                "description": user["name"],
                                "date_played": played_at,
                                "image_url": f"/api/emby/image/{image_id}" if image_id else "",
                            }
                        )

            media_count = sum(int(counts.get(key) or 0) for key in ("MovieCount", "SeriesCount", "EpisodeCount", "SongCount", "AlbumCount"))
            movie_count = int(counts.get("MovieCount") or 0)
            series_count = int(counts.get("SeriesCount") or 0)
            add_log("info", "emby", "Emby 看板数据同步完成", {"libraries": len(libraries), "users": len(users), "history": len(history)})
            return {
                "media_count": media_count,
                "movie_count": movie_count,
                "series_count": series_count,
                "counts": counts,
                "libraries": libraries,
                "users": users,
                "history": sorted(history, key=lambda x: x.get("date_played") or "", reverse=True)[:16],
            }
        except Exception as exc:
            add_log("error", "emby", "Emby 看板数据获取失败", {"error": str(exc), "server_url": base_url})
            return {"media_count": 0, "libraries": [], "users": [], "history": [], "error": str(exc)}

    async def image_response(self, item_id: str) -> tuple[bytes, str]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return b"", "image/jpeg"
        proxy = module_proxy("emby")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=20, follow_redirects=True) as client:
            res = await client.get(f"{base_url}/Items/{item_id}/Images/Primary", params={"api_key": api_key, "maxWidth": 480}, headers={"X-Emby-Token": api_key})
            res.raise_for_status()
            return res.content, res.headers.get("content-type", "image/jpeg")

    async def user_image_response(self, user_id: str) -> tuple[bytes, str]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return b"", "image/jpeg"
        proxy = module_proxy("emby")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=20, follow_redirects=True) as client:
            res = await client.get(f"{base_url}/Users/{user_id}/Images/Primary", params={"api_key": api_key, "maxWidth": 240}, headers={"X-Emby-Token": api_key})
            res.raise_for_status()
            return res.content, res.headers.get("content-type", "image/jpeg")
