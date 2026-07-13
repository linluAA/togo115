from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from telethon import functions
from telethon.errors import RPCError

from app.db import add_log


class _TelegramWebAppMixin:
    async def webapp_auth_data(self, bot_username: str, webapp_url: str | None = None, start_param: str | None = None) -> dict[str, Any]:
        bot = str(bot_username or "").strip().lstrip("@")
        if not bot:
            raise RuntimeError("Telegram bot username is required")
        if not await self.is_authorized():
            raise RuntimeError("Telegram is not logged in")

        client = await self.client()
        bot_entity = await client.get_input_entity(bot)
        webview = await client(
            functions.messages.RequestWebViewRequest(
                peer=bot_entity,
                bot=bot_entity,
                platform="web",
                from_bot_menu=not bool(webapp_url),
                url=webapp_url or None,
                start_param=start_param or None,
            )
        )
        url = str(getattr(webview, "url", "") or "")
        auth_data = _telegram_webapp_init_data(url)
        if not auth_data:
            raise RuntimeError("tgWebAppData was not found in Telegram WebApp URL")
        add_log("info", "telegram", "Telegram WebApp auth data fetched", {"bot": bot, "url_host": urlparse(url).netloc})
        return {"ok": True, "bot": bot, "url": url, "auth_data": auth_data}

    async def url_auth_login(self, auth_url: str) -> dict[str, Any]:
        url = str(auth_url or "").strip()
        if not url:
            raise RuntimeError("Telegram auth URL is required")
        if not await self.is_authorized():
            raise RuntimeError("Telegram is not logged in")

        client = await self.client()
        try:
            preview = await client(functions.messages.RequestUrlAuthRequest(url=url))
            accepted = await client(functions.messages.AcceptUrlAuthRequest(url=url, write_allowed=True))
        except RPCError as exc:
            raise RuntimeError(_telegram_oauth_error_message(exc)) from exc
        except Exception as exc:
            raise RuntimeError(_telegram_oauth_error_message(exc)) from exc
        redirect_url = str(getattr(accepted, "url", "") or url)
        add_log("info", "telegram", "Telegram OAuth authorization accepted", {"domain": getattr(preview, "domain", urlparse(url).netloc), "redirect_host": urlparse(redirect_url).netloc})
        return {"ok": True, "url": redirect_url}


def _telegram_webapp_init_data(url: str) -> str:
    parsed = urlparse(str(url or ""))
    for part in (parsed.fragment, parsed.query):
        params = parse_qs(part, keep_blank_values=True)
        value = params.get("tgWebAppData") or params.get("initData")
        if value:
            return value[0]
    return ""


def _telegram_oauth_error_message(exc: Exception) -> str:
    raw = str(exc).strip()
    name = exc.__class__.__name__
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    detail = raw or str(message or "").strip() or repr(exc)
    if name == "UrlAuthExceptionError":
        return "Telegram rejected this web login authorization"
    if name == "AuthKeyUnregisteredError":
        return "Telegram session expired; log in again"
    if name == "SessionPasswordNeededError":
        return "Telegram account requires two-step verification"
    if name in {"ConnectTimeout", "TimeoutError"} or "timeout" in detail.lower():
        return "Telegram OAuth connection timed out"
    suffix = f" ({name}{f' {code}' if code else ''})"
    return f"Telegram OAuth login failed: {detail}{suffix}"
