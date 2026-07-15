from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from app.auth import current_user
from app.services.log_queries import list_logs
from app.services.search_metrics import metrics_snapshot


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


@router.get("/api/metrics/search")
async def search_metrics(user: dict = Depends(current_user)) -> dict:
    return await asyncio.to_thread(metrics_snapshot)
