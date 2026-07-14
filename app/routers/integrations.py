from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import current_user
from app.schemas import (
    Pan115QrRequest,
    Pan115SaveRequest,
    TelegramCodeLoginRequest,
    TelegramCodeRequest,
)
from app.services.integration_actions import (
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
