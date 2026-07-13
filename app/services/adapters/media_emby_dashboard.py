from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.db import add_log
from app.services.integration_state import get_setting, module_proxy


class EmbyDashboardMixin:
    async def dashboard(self) -> dict[str, Any]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return {"media_count": 0, "libraries": [], "users": [], "history": []}
        try:
            return await self._fetch_dashboard(base_url, api_key, module_proxy("emby"))
        except Exception as exc:
            add_log("error", "emby", "Emby 看板数据获取失败", {"error": str(exc), "server_url": base_url})
            return {"media_count": 0, "libraries": [], "users": [], "history": [], "error": str(exc)}

    async def _fetch_dashboard(self, base_url: str, api_key: str, proxy: str | None) -> dict[str, Any]:
        async with httpx.AsyncClient(proxy=proxy or None, timeout=20, follow_redirects=True) as client:
            counts, folders, users_raw = await asyncio.gather(
                self._get(client, base_url, "/Items/Counts", api_key),
                self._get(client, base_url, "/Library/VirtualFolders", api_key),
                self._get(client, base_url, "/Users", api_key),
            )
            libraries = self._libraries(folders)
            users = self._users(users_raw)
            history = await self._history(client, base_url, api_key, users)
        media_count = sum(int(counts.get(key) or 0) for key in ("MovieCount", "SeriesCount", "EpisodeCount", "SongCount", "AlbumCount"))
        add_log("info", "emby", "Emby 看板数据同步完成", {"libraries": len(libraries), "users": len(users), "history": len(history)})
        return {
            "media_count": media_count,
            "movie_count": int(counts.get("MovieCount") or 0),
            "series_count": int(counts.get("SeriesCount") or 0),
            "counts": counts,
            "libraries": libraries,
            "users": users,
            "history": sorted(history, key=lambda x: x.get("date_played") or "", reverse=True)[:16],
        }

    def _libraries(self, folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return libraries

    def _users(self, users_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": user.get("Id"),
                "name": user.get("Name") or "用户",
                "description": "已禁用" if user.get("Policy", {}).get("IsDisabled") else "正常",
                "image_url": f"/api/emby/user-image/{user.get('Id')}" if user.get("Id") else "",
            }
            for user in users_raw
        ]

    async def _history(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        users: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        tasks = [self._fetch_user_history(client, base_url, api_key, user) for user in users if user.get("id")]
        for item in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(item, Exception):
                add_log("warning", "emby", "Emby 用户观看历史读取失败", {"error": str(item)})
                continue
            user, played = item
            history.extend(self._history_items(user, played.get("Items", [])))
        return history

    async def _fetch_user_history(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        user: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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
        if played.get("Items"):
            return user, played
        resume = await self._get(
            client,
            base_url,
            f"/Users/{user['id']}/Items/Resume",
            api_key,
            {
                "Limit": 12,
                "MediaTypes": "Video",
                "Fields": "DatePlayed,DateCreated,PrimaryImageAspectRatio,SeriesName,UserData",
                "EnableUserData": "true",
            },
        )
        return (user, resume) if resume.get("Items") else (user, played)

    def _history_items(self, user: dict[str, Any], media_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        history = []
        for media in media_items:
            played_at = self._played_at(media)
            if not played_at:
                continue
            image_id = media.get("SeriesId") or media.get("Id")
            title = media.get("SeriesName") or media.get("Name") or "媒体"
            history.append(
                {
                    "id": media.get("Id"),
                    "name": media.get("Name") or "媒体",
                    "title": title,
                    "description": user["name"],
                    "date_played": played_at,
                    "image_url": f"/api/emby/image/{image_id}" if image_id else "",
                }
            )
        return history

    def _played_at(self, media: dict[str, Any]) -> str:
        user_data = media.get("UserData", {})
        return user_data.get("LastPlayedDate") or media.get("DatePlayed") or media.get("DateCreated") or ""
