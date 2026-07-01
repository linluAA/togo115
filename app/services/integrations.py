import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunparse

import httpx
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

from app.config import settings
from app.db import add_log, db, json_dumps, json_loads, utc_now

PAN115_URL_RE = re.compile(r"https?://(?:www\.)?115(?:cdn)?\.com/s/[A-Za-z0-9_-]+(?:\?[^\s\"'<>)]+)?", re.I)
MAGNET_URL_RE = re.compile(r"magnet:\?[^\s\"'<>)]+", re.I)
TORRENT_URL_RE = re.compile(r"https?://[^\s\"'<>)]+?\.torrent(?:\?[^\s\"'<>)]+)?", re.I)


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


def _split_filter_words(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,，\n\r]+", str(value or "")) if part.strip()]


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


def extract_download_links(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    links: list[str] = []
    for pattern in (PAN115_URL_RE, MAGNET_URL_RE, TORRENT_URL_RE):
        for match in pattern.findall(text):
            link = match.rstrip("，。；,.;")
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "enabled")


def context_for_115_link(text: str | None, link: str, total_links: int) -> str:
    message = text or ""
    if not message or total_links <= 1:
        return message
    lines = message.splitlines()
    for index, line in enumerate(lines):
        if link in line:
            context_lines = []
            if index > 0:
                context_lines.append(lines[index - 1])
            context_lines.append(line)
            if index + 1 < len(lines) and re.search(r"(?i)(pwd|pass|密码|提取码|访问码|口令)", lines[index + 1]):
                context_lines.append(lines[index + 1])
            return "\n".join(part for part in context_lines if part.strip())
    position = message.find(link)
    if position < 0:
        return message[:500]
    start = max(0, position - 160)
    end = min(len(message), position + len(link) + 160)
    return message[start:end]


def _first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            return (child.text or "").strip()
    return ""


def _all_text(element: ET.Element, names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            value = (child.text or "").strip()
            if value:
                values.append(value)
    return values


def _item_links(element: ET.Element, allow_direct_http: bool = False) -> list[str]:
    text_candidates: list[str] = []
    direct_candidates: list[str] = []

    def _looks_like_direct_download(url: str) -> bool:
        lowered = url.strip().casefold()
        return lowered.startswith("magnet:?") or lowered.endswith(".torrent") or any(marker in lowered for marker in ("/download", "download?", "getfile", "attachment", "fileid="))

    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name == "link":
            href = child.attrib.get("href")
            if href:
                if allow_direct_http and _looks_like_direct_download(href):
                    direct_candidates.append(href.strip())
                else:
                    text_candidates.append(href.strip())
            if child.text:
                if allow_direct_http and _looks_like_direct_download(child.text):
                    direct_candidates.append(child.text.strip())
                else:
                    text_candidates.append(child.text.strip())
        if local_name in ("enclosure", "torznab"):
            url = child.attrib.get("url")
            if url:
                direct_candidates.append(url.strip())
        if local_name == "attr":
            name = child.attrib.get("name", "").casefold()
            value = child.attrib.get("value")
            if value:
                if name in ("magneturl", "downloadurl", "download", "torrent", "link"):
                    direct_candidates.append(value.strip())
                else:
                    text_candidates.append(value.strip())
    links: list[str] = []
    for candidate in text_candidates:
        links.extend(extract_download_links(candidate))
    for candidate in direct_candidates:
        extracted = extract_download_links(candidate)
        links.extend(extracted or ([candidate] if allow_direct_http and candidate.startswith(("http://", "https://", "magnet:?")) else []))
    seen: set[str] = set()
    deduped: list[str] = []
    for link in links:
        cleaned = link.rstrip("，。；,.;")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(cleaned)
    return deduped


def _item_context(element: ET.Element) -> str:
    parts = [
        _first_text(element, ("title",)),
        _first_text(element, ("description", "summary", "content", "encoded")),
        *_all_text(element, ("category",)),
    ]
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name == "attr":
            name = child.attrib.get("name", "")
            value = child.attrib.get("value", "")
            if name or value:
                parts.append(f"{name}: {value}")
    return "\n".join(part for part in parts if part)


class RssTorznabAdapter:
    def _source_identity(self, source: dict[str, Any]) -> str:
        return str(source.get("id") or f"{source.get('name') or ''}|{source.get('url') or ''}")

    def _source_supports_query(self, source: dict[str, Any]) -> bool:
        url = str(source.get("url") or "")
        return "{query}" in url or "{title}" in url or str(source.get("type") or "").lower() == "torznab"

    def _sources(self) -> list[dict[str, Any]]:
        config = get_setting("rss_sources", {"sources": []})
        sources = config.get("sources") or []
        return [source for source in sources if isinstance(source, dict) and _truthy(source.get("enabled"), True)]

    def _source_proxy(self, source: dict[str, Any]) -> str | None:
        if _truthy(source.get("use_proxy")):
            proxy = get_setting("proxy")
            return proxy.get("url")
        return None

    def _source_url(self, source: dict[str, Any], query: str | None = None) -> str | None:
        url = str(source.get("url") or "").strip()
        if not url:
            return None
        if "{query}" in url or "{title}" in url:
            if not query:
                return None
            encoded = quote(query)
            return url.replace("{query}", encoded).replace("{title}", encoded)
        if query and str(source.get("type") or "").lower() == "torznab":
            parsed = urlparse(url)
            params = parse_qsl(parsed.query, keep_blank_values=True)
            keys = {key.lower() for key, _ in params}
            if "t" not in keys:
                params.append(("t", "search"))
            if "q" not in keys:
                params.append(("q", query))
            return urlunparse(parsed._replace(query=urlencode(params)))
        return url

    def _source_matches_filters(self, source: dict[str, Any], text: str) -> bool:
        raw = text.casefold()
        required_keywords = _split_filter_words(source.get("keywords"))
        quality_keywords = _split_filter_words(source.get("quality"))
        if required_keywords and not all(keyword.casefold() in raw for keyword in required_keywords):
            return False
        if quality_keywords and not any(keyword.casefold() in raw for keyword in quality_keywords):
            return False
        return True

    async def search_history(self, title: str, keywords: list[str]) -> list[SearchResult]:
        sources = self._sources()
        if not sources:
            return []
        results: list[SearchResult] = []
        clean_keywords = [item.strip() for item in keywords if item and item.strip() and item.strip() != title]
        queries = [title, *(f"{title} {keyword}" for keyword in clean_keywords)]
        for source in sources:
            if self._source_supports_query(source):
                for query in dict.fromkeys(queries):
                    results.extend(await self._fetch_source(source, query))
            else:
                results.extend(await self._fetch_source(source))
        deduped = self._dedupe_results(results)
        add_log("info", "rss", "RSS/Torznab 订阅源搜索完成", {"count": len(deduped), "sources": len(sources), "title": title})
        return deduped

    async def fetch_due_sources(self, queries: list[str] | None = None) -> list[SearchResult]:
        now = time.time()
        sources = []
        for source in self._sources():
            try:
                last_checked = float(source.get("last_checked_at") or 0)
            except (TypeError, ValueError):
                last_checked = 0
            try:
                interval_minutes = int(source.get("refresh_interval") or 30)
            except (TypeError, ValueError):
                interval_minutes = 30
            interval = max(interval_minutes, 5) * 60
            if now - last_checked >= interval:
                sources.append(source)
        results: list[SearchResult] = []
        updated = False
        search_queries = list(dict.fromkeys(query.strip() for query in (queries or []) if query and query.strip()))
        for source in sources:
            if self._source_supports_query(source):
                source_queries: list[str | None] = search_queries
            else:
                source_queries = [None]
            if not source_queries:
                continue
            for query in source_queries:
                source_results = await self._fetch_source(source, query)
                results.extend(source_results)
            source["last_checked_at"] = now
            updated = True
        if updated:
            config = get_setting("rss_sources", {"sources": []})
            configured = config.get("sources") or []
            checked_by_id = {self._source_identity(source): source.get("last_checked_at") for source in sources}
            for item in configured:
                identity = self._source_identity(item)
                if identity in checked_by_id:
                    item["last_checked_at"] = checked_by_id[identity]
            save_setting("rss_sources", {**config, "sources": configured})
        results = self._dedupe_results(results)
        if results:
            add_log("info", "rss", "RSS/Torznab 定时刷新完成", {"count": len(results), "sources": len(sources)})
        return results

    async def _fetch_source(self, source: dict[str, Any], query: str | None = None) -> list[SearchResult]:
        name = str(source.get("name") or "RSS/Torznab").strip()
        url = self._source_url(source, query)
        if not url:
            return []
        try:
            async with httpx.AsyncClient(proxy=self._source_proxy(source), timeout=25, follow_redirects=True) as client:
                res = await client.get(url, headers={"User-Agent": "ToGo115/1.0"})
            res.raise_for_status()
            return self._parse_feed(source, res.text)
        except Exception as exc:
            add_log("warning", "rss", "RSS/Torznab 订阅源读取失败", {"source": name, "url": url, "error": str(exc)})
            return []

    def _parse_feed(self, source: dict[str, Any], xml_text: str) -> list[SearchResult]:
        name = str(source.get("name") or "RSS/Torznab").strip()
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            add_log("warning", "rss", "RSS/Torznab 解析失败", {"source": name, "error": str(exc)})
            return []
        items = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1].lower() in ("item", "entry")]
        results: list[SearchResult] = []
        for item in items:
            title = _first_text(item, ("title",)) or name
            context = _item_context(item)
            text = context or title
            if not self._source_matches_filters(source, text):
                continue
            source_type = str(source.get("type") or "rss").lower()
            links = _item_links(item, allow_direct_http=source_type == "torznab") or extract_download_links(text)
            for link in links:
                results.append(
                    SearchResult(
                        title=title[:120],
                        url=link,
                        source=f"{source_type}:{name}",
                        message_id=_first_text(item, ("guid", "id")),
                        context=text,
                    )
                )
        return results

    def _dedupe_results(self, results: list[SearchResult]) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            key = (result.source, result.url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped


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
    _handler = None
    _handler_sources: tuple[str, ...] = ()

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
        deduped: list[SearchResult] = []
        seen: set[tuple[str, str | None, str]] = set()
        for result in results:
            key = (result.source, result.message_id, result.url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        add_log("info", "telegram", "Telegram 历史搜索完成", {"title": title, "count": len(deduped), "raw_count": len(results)})
        return deduped

    async def _links_from_message(self, client: TelegramClient, message: Any, source: str) -> list[SearchResult]:
        message_text = message.raw_text or ""
        direct_links = extract_115_links(message_text)
        link_contexts: dict[str, str] = {
            link: context_for_115_link(message_text, link, len(direct_links))
            for link in direct_links
        }
        if getattr(message, "buttons", None):
            button_links = await self._click_buttons_for_links(message)
            use_message_context = not direct_links and len(button_links) == 1
            for link, button_text in button_links:
                context = "\n".join(
                    part for part in ((message_text if use_message_context else ""), button_text) if part
                )
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
        link_button_words = ("115", "链接", "查看", "打开", "资源", "获取", "下载", "提取", "网盘", "详情", "link")
        for row_index, row in enumerate(message.buttons or []):
            for col_index, button in enumerate(row):
                label = getattr(button, "text", "") or ""
                if not any(word in label.casefold() for word in link_button_words):
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
        client = await self.client()
        config = self._config()
        dialogs = [x.strip() for x in str(config.get("sources", "")).split(",") if x.strip()]
        if not dialogs:
            return
        source_key = tuple(dialogs)
        listener_alive = bool(cls._listener_task and not cls._listener_task.done())
        if listener_alive and cls._handler_registered and cls._handler_sources == source_key:
            add_log("debug", "telegram", "Telegram 监控心跳正常")
            return

        if cls._handler_registered and cls._handler is not None:
            client.remove_event_handler(cls._handler)
            source_changed = cls._handler_sources != source_key
            cls._handler_registered = False
            cls._handler = None
            cls._handler_sources = ()
            add_log("info", "telegram", "Telegram 监控来源已变更，重新注册监听" if source_changed else "Telegram 监控连接已重建，重新注册监听", {"sources": dialogs})

        if not cls._handler_registered:
            async def handler(event) -> None:
                from app.services.subscription import attach_results_to_matching_subscriptions

                results = await self._links_from_message(client, event.message, str(event.chat_id))
                if results:
                    await attach_results_to_matching_subscriptions(results, event.message.raw_text or "")

            client.add_event_handler(handler, events.NewMessage(chats=dialogs))
            cls._handler_registered = True
            cls._handler = handler
            cls._handler_sources = source_key

        if not listener_alive:
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
    _polling_task: asyncio.Task | None = None
    _polling_token: str | None = None

    def _config(self) -> dict[str, Any]:
        return get_setting("tg_bot")

    def _api_url(self, token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    def _chat_allowed(self, config: dict[str, Any], chat_id: int | str | None) -> bool:
        allowed = str(config.get("allowed_chat_id") or "").strip()
        return not allowed or str(chat_id) == allowed

    async def ensure_polling(self) -> None:
        config = self._config()
        token = str(config.get("bot_token") or "").strip()
        if not token:
            return
        cls = type(self)
        if cls._polling_task and not cls._polling_task.done() and cls._polling_token != token:
            await self.stop_polling()
        if cls._polling_task and not cls._polling_task.done():
            add_log("debug", "tg_bot", "TG Bot 监听心跳正常")
            return
        cls._polling_token = token
        cls._polling_task = asyncio.create_task(self._poll_updates(token), name="togo115-tg-bot")
        add_log("info", "tg_bot", "TG Bot 监听已启动")

    async def stop_polling(self) -> None:
        cls = type(self)
        if cls._polling_task and not cls._polling_task.done():
            cls._polling_task.cancel()
            try:
                await cls._polling_task
            except asyncio.CancelledError:
                pass
        cls._polling_task = None
        cls._polling_token = None

    async def _poll_updates(self, token: str) -> None:
        offset = int(get_flow("tg_bot").get("offset") or 0)
        proxy = module_proxy("telegram")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=35, follow_redirects=True) as client:
            while True:
                try:
                    res = await client.get(self._api_url(token, "getUpdates"), params={"timeout": 25, "offset": offset})
                    res.raise_for_status()
                    payload = res.json()
                    if not payload.get("ok"):
                        add_log("warning", "tg_bot", "TG Bot 获取消息失败", {"response": payload})
                        await asyncio.sleep(5)
                        continue
                    for update in payload.get("result", []):
                        offset = int(update.get("update_id") or offset) + 1
                        save_flow("tg_bot", {"offset": offset})
                        await self._handle_update(client, token, update)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    add_log("warning", "tg_bot", "TG Bot 监听异常，稍后重试", {"error": str(exc)})
                    await asyncio.sleep(5)

    async def _handle_update(self, client: httpx.AsyncClient, token: str, update: dict[str, Any]) -> None:
        callback = update.get("callback_query") or {}
        if callback:
            await self._handle_callback(client, token, callback)
            return
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return
        config = self._config()
        if not self._chat_allowed(config, chat_id):
            await self._send_bot_message(client, token, chat_id, "当前 Chat ID 未授权。")
            add_log("warning", "tg_bot", "TG Bot 收到未授权消息", {"chat_id": chat_id})
            return
        reply = await self._command_reply(text, chat_id)
        if reply:
            await self._send_bot_message(client, token, chat_id, reply)

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
            try:
                await self._answer_callback(client, token, callback_id, "正在读取详情...")
                _, media_type, tmdb_id = data.split(":", 2)
                await self._send_subscription_preview(client, token, chat_id, media_type, int(tmdb_id))
            except Exception as exc:
                add_log("warning", "tg_bot", "TG Bot 发送订阅详情失败", {"data": data, "error": str(exc)})
                if chat_id:
                    await self._send_bot_message(client, token, chat_id, f"详情获取失败：{str(exc)[:120]}")
            return
        if data.startswith("subscribe:"):
            try:
                await self._answer_callback(client, token, callback_id, "正在添加订阅...")
                _, media_type, tmdb_id = data.split(":", 2)
                detail = await TmdbAdapter().detail(media_type, int(tmdb_id))
                title = detail.get("name") or detail.get("title") or "未命名"
                poster = f"https://image.tmdb.org/t/p/w500{detail.get('poster_path')}" if detail.get("poster_path") else None
                from app.services.subscription import create_subscription
                from app.schemas import SubscriptionCreate

                subscription = await create_subscription(
                    SubscriptionCreate(
                        title=title,
                        media_type=media_type,
                        tmdb_id=int(tmdb_id),
                        poster_url=poster,
                        overview=detail.get("overview") or "",
                        tmdb_total_count=detail.get("number_of_episodes") or 0,
                        keywords=[title],
                    )
                )
                if chat_id:
                    await self._send_bot_message(client, token, chat_id, f"已添加订阅：{subscription.get('title')}，ID {subscription.get('id')}")
                await self._clear_message_buttons(client, token, message)
            except Exception as exc:
                add_log("warning", "tg_bot", "TG Bot 回调订阅失败", {"data": data, "error": str(exc)})
                if chat_id:
                    await self._send_bot_message(client, token, chat_id, f"订阅失败：{str(exc)[:120]}")
            return
        if data == "cancel_preview":
            await self._answer_callback(client, token, callback_id, "已取消")
            await self._clear_message_buttons(client, token, message)
            return
        await self._answer_callback(client, token, callback_id, "未知操作")

    async def _command_reply(self, text: str, chat_id: int | str) -> str:
        from app.services.subscription import delete_subscription, list_subscriptions

        command, args = self._parse_bot_command(text)
        command = command.split("@", 1)[0].lower()
        if command in ("/start", "/help", "help", "帮助"):
            return "可用命令：\n/list 或 订阅列表\n订阅 剧名：搜索剧集并选择海报订阅\n取消订阅 名称/ID\n/id 查看当前 Chat ID"
        if command in ("/id", "id"):
            return f"当前 Chat ID：{chat_id}"
        if command in ("/list", "list", "订阅列表", "列表"):
            subscriptions = list_subscriptions()
            if not subscriptions:
                return "暂无订阅。"
            lines = ["订阅列表："]
            for item in subscriptions[:30]:
                status = "完成" if item.get("status") == "completed" else item.get("status", "")
                if item.get("media_type") == "tv":
                    count = int(item.get("emby_count") or 0)
                    total = int(item.get("tmdb_total_count") or 0)
                    progress = f"{count}/{total}集" if total else f"{count}集"
                    status = f"完成 {progress}" if item.get("status") == "completed" else progress
                lines.append(f"{item['id']}. {item['title']} ({'剧集' if item['media_type'] == 'tv' else '电影'} {status})")
            return "\n".join(lines)
        if command in ("/search", "/subscribe", "search", "subscribe", "订阅", "搜索"):
            if not args:
                return "请输入要订阅的剧名，例如：订阅 斗罗大陆"
            await self._send_subscription_choices(chat_id, args)
            return ""
        if command in ("/cancel", "cancel", "取消订阅", "取消"):
            if not args:
                return "请输入订阅名称或 ID，例如：取消订阅 斗罗大陆"
            if args.split()[0].isdigit():
                delete_subscription(int(args.split()[0]))
                return "已取消订阅。"
            from app.services.subscription import delete_subscription_by_title
            deleted = delete_subscription_by_title(args)
            return f"已取消 {deleted} 个订阅。" if deleted else "没有找到匹配的订阅。"
        return "未知命令。发送 /help 查看可用命令。"

    def _parse_bot_command(self, text: str) -> tuple[str, str]:
        text = text.strip()
        for prefix in ("取消订阅", "订阅", "搜索", "取消"):
            if text == prefix:
                return prefix, ""
            if text.startswith(prefix):
                return prefix, text[len(prefix):].strip()
        command, *rest = text.split(maxsplit=1)
        return command, rest[0].strip() if rest else ""

    async def _send_bot_message(self, client: httpx.AsyncClient, token: str, chat_id: int | str, text: str) -> None:
        res = await client.post(self._api_url(token, "sendMessage"), data={"chat_id": chat_id, "text": text[:3900]})
        if res.status_code >= 400:
            add_log("warning", "tg_bot", "TG Bot 回复消息失败", {"status": res.status_code, "body": res.text[:240]})

    async def _send_subscription_choices(self, chat_id: int | str, query: str) -> None:
        config = self._config()
        token = str(config.get("bot_token") or "").strip()
        if not token:
            return
        results = await TmdbAdapter().search(query, "tv")
        proxy = module_proxy("telegram")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=25, follow_redirects=True) as client:
            if not results:
                await self._send_bot_message(client, token, chat_id, f"没有搜索到：{query}")
                return
            buttons = []
            lines = [f"搜索到 {min(len(results), 8)} 个结果，请选择剧集查看详情："]
            for index, item in enumerate(results[:8], start=1):
                title = item.get("name") or item.get("title") or "未命名"
                year = str(item.get("first_air_date") or "")[:4] or "未知年份"
                lines.append(f"{index}. {title} ({year})")
                buttons.append([{"text": f"{index}. {title[:28]}", "callback_data": f"preview:tv:{item.get('id')}"}])
            reply_markup = {"inline_keyboard": buttons}
            res = await client.post(
                self._api_url(token, "sendMessage"),
                data={"chat_id": chat_id, "text": "\n".join(lines)[:3900], "reply_markup": json_dumps(reply_markup)},
            )
            if res.status_code >= 400:
                add_log("warning", "tg_bot", "TG Bot 发送订阅候选失败", {"status": res.status_code, "body": res.text[:240]})

    async def _send_subscription_preview(self, client: httpx.AsyncClient, token: str, chat_id: int | str | None, media_type: str, tmdb_id: int) -> None:
        if not chat_id:
            return
        detail = await TmdbAdapter().detail(media_type, tmdb_id)
        title = detail.get("name") or detail.get("title") or "未命名"
        year = str(detail.get("first_air_date") or detail.get("release_date") or "")[:4] or "未知年份"
        total = detail.get("number_of_episodes")
        overview = detail.get("overview") or "暂无简介"
        facts = f"{year}" + (f" · {total} 集" if total else "")
        caption = f"{title}\n{facts}\n\n{overview[:520]}"
        reply_markup = {
            "inline_keyboard": [[
                {"text": "确认订阅", "callback_data": f"subscribe:{media_type}:{tmdb_id}"},
                {"text": "取消", "callback_data": "cancel_preview"},
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
            add_log("warning", "tg_bot", "TG Bot 发送订阅详情失败", {"status": res.status_code, "body": res.text[:240]})

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
            add_log("debug", "tg_bot", "TG Bot 清除详情按钮失败", {"status": res.status_code, "body": res.text[:240]})

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
