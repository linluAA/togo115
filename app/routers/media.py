from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import current_user
from app.services.media_catalog import (
    emby_dashboard as get_emby_dashboard,
    emby_image as get_emby_image,
    emby_user_image as get_emby_user_image,
    tmdb_detail as get_tmdb_detail,
    tmdb_search as search_tmdb,
    tmdb_trending as get_tmdb_trending,
)

router = APIRouter()


@router.get("/api/tmdb/trending")
async def tmdb_trending(limit: int = 20, user: dict = Depends(current_user)) -> dict:
    return await get_tmdb_trending(limit=limit)


@router.get("/api/tmdb/search")
async def tmdb_search(q: str, media_type: str = "multi", user: dict = Depends(current_user)) -> dict:
    return await search_tmdb(q, media_type)


@router.get("/api/tmdb/{media_type}/{tmdb_id}")
async def tmdb_detail(media_type: str, tmdb_id: int, user: dict = Depends(current_user)) -> dict:
    if media_type not in ("tv", "movie"):
        raise HTTPException(status_code=400, detail="不支持的媒体类型")
    return await get_tmdb_detail(media_type, tmdb_id)


@router.get("/api/emby/dashboard")
async def emby_dashboard(user: dict = Depends(current_user)) -> dict:
    return await get_emby_dashboard()


@router.get("/api/emby/image/{item_id}")
async def emby_image(item_id: str, user: dict = Depends(current_user)) -> StreamingResponse:
    content, media_type = await get_emby_image(item_id)
    return StreamingResponse(BytesIO(content), media_type=media_type)


@router.get("/api/emby/user-image/{user_id}")
async def emby_user_image(user_id: str, user: dict = Depends(current_user)) -> StreamingResponse:
    content, media_type = await get_emby_user_image(user_id)
    return StreamingResponse(BytesIO(content), media_type=media_type)
