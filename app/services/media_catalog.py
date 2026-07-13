from __future__ import annotations

from app.services.adapters.media import EmbyAdapter, TmdbAdapter


async def tmdb_trending(limit: int = 20) -> dict:
    return await TmdbAdapter().trending(limit=limit)


async def tmdb_search(query: str, media_type: str = "multi") -> dict:
    return {"results": await TmdbAdapter().search(query, media_type)}


async def tmdb_detail(media_type: str, tmdb_id: int) -> dict:
    return await TmdbAdapter().detail(media_type, tmdb_id)


async def emby_dashboard() -> dict:
    return await EmbyAdapter().dashboard()


async def emby_image(item_id: str) -> tuple[bytes, str]:
    return await EmbyAdapter().image_response(item_id)


async def emby_user_image(user_id: str) -> tuple[bytes, str]:
    return await EmbyAdapter().user_image_response(user_id)
