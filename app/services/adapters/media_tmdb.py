from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from app.services.integration_state import get_setting, module_proxy


class TmdbAdapter:
    async def _client(self) -> httpx.AsyncClient:
        proxy = module_proxy("tmdb")
        return httpx.AsyncClient(proxy=proxy or None, timeout=20)

    def _api_key(self) -> str | None:
        return get_setting("tmdb").get("api_key")

    async def trending(self, limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        api_key = self._api_key()
        if not api_key:
            return {"tv": [], "movie": []}
        limit = max(1, min(int(limit or 20), 300))
        async with await self._client() as client:
            tv, movie = await asyncio.gather(
                self._trending_items(client, "tv", api_key, limit),
                self._trending_items(client, "movie", api_key, limit),
            )
        return {"tv": tv, "movie": movie}

    async def _trending_items(
        self,
        client: httpx.AsyncClient,
        media_type: str,
        api_key: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        page_count = max(1, min(15, math.ceil(max(limit, 1) / 20)))
        endpoint = f"https://api.themoviedb.org/3/trending/{media_type}/week"
        semaphore = asyncio.Semaphore(5)

        async def fetch_page(page: int) -> list[dict[str, Any]]:
            async with semaphore:
                res = await client.get(endpoint, params={"api_key": api_key, "language": "zh-CN", "page": page})
                res.raise_for_status()
                return res.json().get("results", [])

        pages = await asyncio.gather(*(fetch_page(page) for page in range(1, page_count + 1)))
        items: list[dict[str, Any]] = []
        seen: set[int] = set()
        for page_items in pages:
            for item in page_items:
                item_id = item.get("id")
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)
                items.append(item)
                if len(items) >= limit:
                    return items
        return items

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
