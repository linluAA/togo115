from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import current_user
from app.schemas import BotCommand
from app.services.log_queries import list_logs
from app.services.subscription_crud import delete_subscription, list_subscriptions


router = APIRouter()


@router.get("/api/logs")
async def logs(
    mode: str = "simple",
    limit: int = Query(100, ge=1, le=300),
    before_id: int | None = Query(None, ge=1),
    after_id: int | None = Query(None, ge=1),
    user: dict = Depends(current_user),
) -> list[dict]:
    return await asyncio.to_thread(list_logs, mode=mode, limit=limit, before_id=before_id, after_id=after_id)


@router.post("/api/bot/command")
async def bot_command(payload: BotCommand) -> dict:
    command = payload.command.strip().lower()
    if command in ("/list", "list"):
        return {"subscriptions": list_subscriptions()}
    if command in ("/subscribe", "subscribe"):
        query = str(payload.args.get("query") or payload.args.get("title") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="请传入 query")
        return {"message": "请通过 Telegram Bot 发送“订阅 剧名”并在搜索结果中选择订阅", "query": query}
    if command in ("/cancel", "cancel"):
        delete_subscription(int(payload.args["id"]))
        return {"ok": True}
    return {"error": "未知命令"}
