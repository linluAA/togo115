from __future__ import annotations

from app.db import add_log
from app.services.adapters.pan115 import Pan115Adapter
from app.services.adapters.telegram import TelegramClientAdapter
from app.services.hdhive_browser import (
    hdhive_browser_click,
    hdhive_browser_close,
    hdhive_browser_key,
    hdhive_browser_navigate,
    hdhive_browser_reset,
    hdhive_browser_snapshot,
    hdhive_browser_type,
    open_hdhive_embedded_browser,
)


async def telegram_qr_login_start() -> dict:
    try:
        return await TelegramClientAdapter().qr_login_start()
    except Exception as exc:
        add_log("error", "telegram", "Telegram 扫码登录创建失败", {"error": str(exc)})
        raise


async def telegram_send_login_code(phone: str) -> dict:
    try:
        return await TelegramClientAdapter().send_login_code(phone)
    except Exception as exc:
        add_log("error", "telegram", "Telegram 手机验证码发送失败", {"error": str(exc)})
        raise


async def telegram_sign_in_code(phone: str, code: str) -> dict:
    try:
        return await TelegramClientAdapter().sign_in_code(phone, code)
    except Exception as exc:
        add_log("error", "telegram", "Telegram 手机验证码登录失败", {"error": str(exc)})
        raise


async def telegram_login_status() -> dict:
    return await TelegramClientAdapter().login_status()


async def telegram_dialogs() -> dict:
    return {"dialogs": await TelegramClientAdapter().dialogs()}


async def telegram_webapp_auth_data(bot_username: str, webapp_url: str | None = None, start_param: str | None = None) -> dict:
    try:
        return await TelegramClientAdapter().webapp_auth_data(bot_username, webapp_url, start_param)
    except Exception as exc:
        add_log("error", "telegram", "Telegram WebApp 授权数据获取失败", {"bot": bot_username, "error": str(exc)})
        raise


async def telegram_url_auth_login(auth_url: str) -> dict:
    try:
        return await TelegramClientAdapter().url_auth_login(auth_url)
    except Exception as exc:
        add_log("error", "telegram", "Telegram OAuth 登录失败", {"error": _error_message(exc)})
        raise


async def pan115_qr_login_start(channel: str) -> dict:
    try:
        return await Pan115Adapter().qr_login_start(channel)
    except Exception as exc:
        add_log("error", "115", "115 扫码登录创建失败", {"error": str(exc)})
        raise


async def pan115_qrcode_image(uid: str, channel: str) -> tuple[bytes, str]:
    try:
        return await Pan115Adapter().qrcode_image(uid, channel)
    except Exception as exc:
        add_log("error", "115", "115 二维码图片生成失败", {"error": str(exc), "uid": uid, "channel": channel})
        raise


async def pan115_login_status() -> dict:
    return await Pan115Adapter().qr_login_status()


async def pan115_folders(cid: str) -> dict:
    try:
        return await Pan115Adapter().list_folders(cid)
    except Exception as exc:
        add_log("error", "115", "115 目录列表获取失败", {"error": str(exc), "cid": cid})
        raise


async def pan115_save_link(link: str, target_path: str | None) -> dict:
    ok = await Pan115Adapter().transfer(link, target_path)
    return {"ok": ok}


async def hdhive_login_browser(source: dict) -> dict:
    return await open_hdhive_embedded_browser(source)


async def hdhive_browser_open(source: dict) -> dict:
    return await open_hdhive_embedded_browser(source)


async def hdhive_browser_screen() -> dict:
    return await hdhive_browser_snapshot()


async def hdhive_browser_click_at(x: float, y: float) -> dict:
    return await hdhive_browser_click(x, y)


async def hdhive_browser_type_text(text: str) -> dict:
    return await hdhive_browser_type(text)


async def hdhive_browser_press_key(key: str) -> dict:
    return await hdhive_browser_key(key)


async def hdhive_browser_go(url: str | None) -> dict:
    return await hdhive_browser_navigate(url)


async def hdhive_browser_stop() -> dict:
    return await hdhive_browser_close()


async def hdhive_browser_reset_profile(source: dict) -> dict:
    return await hdhive_browser_reset(source)


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    detail = getattr(exc, "message", None)
    if detail:
        return str(detail)
    return repr(exc)
