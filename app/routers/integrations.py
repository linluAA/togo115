from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import current_user
from app.schemas import (
    HdhiveBrowserClickRequest,
    HdhiveBrowserKeyRequest,
    HdhiveBrowserNavigateRequest,
    HdhiveBrowserOpenRequest,
    HdhiveBrowserTypeRequest,
    HdhiveLoginBrowserRequest,
    Pan115QrRequest,
    Pan115SaveRequest,
    TelegramCodeLoginRequest,
    TelegramCodeRequest,
    TelegramUrlAuthRequest,
    TelegramWebAppAuthRequest,
)
from app.services.integration_actions import (
    hdhive_login_browser as open_hdhive_login_browser,
    pan115_folders as get_pan115_folders,
    pan115_login_status,
    pan115_qr_login_start,
    pan115_qrcode_image as get_pan115_qrcode_image,
    pan115_save_link,
    telegram_dialogs as get_telegram_dialogs,
    telegram_login_status,
    telegram_qr_login_start,
    telegram_send_login_code,
    telegram_sign_in_code,
    telegram_url_auth_login,
    telegram_webapp_auth_data,
    hdhive_browser_click_at,
    hdhive_browser_go,
    hdhive_browser_open,
    hdhive_browser_press_key,
    hdhive_browser_screen,
    hdhive_browser_stop,
    hdhive_browser_type_text,
)

router = APIRouter()


@router.post("/api/telegram/qr-login")
async def telegram_qr_login(user: dict = Depends(current_user)) -> dict:
    try:
        return await telegram_qr_login_start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/telegram/send-code")
async def telegram_send_code(payload: TelegramCodeRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await telegram_send_login_code(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/telegram/code-login")
async def telegram_code_login(payload: TelegramCodeLoginRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await telegram_sign_in_code(payload.phone, payload.code)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/telegram/status")
async def telegram_status(user: dict = Depends(current_user)) -> dict:
    return await telegram_login_status()


@router.get("/api/telegram/dialogs")
async def telegram_dialogs(user: dict = Depends(current_user)) -> dict:
    return await get_telegram_dialogs()


@router.post("/api/telegram/webapp-auth")
async def telegram_webapp_auth(payload: TelegramWebAppAuthRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await telegram_webapp_auth_data(payload.bot_username, payload.webapp_url, payload.start_param)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/telegram/url-auth-login")
async def telegram_url_auth(payload: TelegramUrlAuthRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await telegram_url_auth_login(payload.auth_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/115/qr-login")
async def pan115_qr_login(payload: Pan115QrRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await pan115_qr_login_start(payload.channel)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/115/qrcode-image")
async def pan115_qrcode_image(uid: str, channel: str = "web", user: dict = Depends(current_user)) -> StreamingResponse:
    try:
        content, media_type = await get_pan115_qrcode_image(uid, channel)
        return StreamingResponse(BytesIO(content), media_type=media_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/115/status")
async def pan115_status(user: dict = Depends(current_user)) -> dict:
    return await pan115_login_status()


@router.get("/api/115/folders")
async def pan115_folders(cid: str = "0", user: dict = Depends(current_user)) -> dict:
    try:
        return await get_pan115_folders(cid)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/115/save")
async def pan115_save(payload: Pan115SaveRequest, user: dict = Depends(current_user)) -> dict:
    return await pan115_save_link(payload.link, payload.target_path)


@router.post("/api/hdhive/login-browser")
async def hdhive_login_browser(payload: HdhiveLoginBrowserRequest, user: dict = Depends(current_user)) -> dict:
    return await open_hdhive_login_browser(payload.source)


@router.post("/api/hdhive/browser/open")
async def hdhive_embedded_browser_open(payload: HdhiveBrowserOpenRequest, user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_open(payload.source)


@router.get("/api/hdhive/browser/snapshot")
async def hdhive_embedded_browser_snapshot(user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_screen()


@router.post("/api/hdhive/browser/click")
async def hdhive_embedded_browser_click(payload: HdhiveBrowserClickRequest, user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_click_at(payload.x, payload.y)


@router.post("/api/hdhive/browser/type")
async def hdhive_embedded_browser_type(payload: HdhiveBrowserTypeRequest, user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_type_text(payload.text)


@router.post("/api/hdhive/browser/key")
async def hdhive_embedded_browser_key(payload: HdhiveBrowserKeyRequest, user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_press_key(payload.key)


@router.post("/api/hdhive/browser/navigate")
async def hdhive_embedded_browser_navigate(payload: HdhiveBrowserNavigateRequest, user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_go(payload.url)


@router.post("/api/hdhive/browser/close")
async def hdhive_embedded_browser_close(user: dict = Depends(current_user)) -> dict:
    return await hdhive_browser_stop()
