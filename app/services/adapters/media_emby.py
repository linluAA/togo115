from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.services.adapters.media_emby_dashboard import EmbyDashboardMixin
from app.services.adapters.media_emby_images import EmbyImagesMixin
from app.services.integration_state import get_setting, module_proxy


class EmbyAdapter(EmbyImagesMixin, EmbyDashboardMixin):
    def _base_url(self, config: dict[str, Any]) -> str:
        return str(config.get("server_url", "")).rstrip("/")

    async def _get(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        path: str,
        api_key: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        query = {"api_key": api_key, **(params or {})}
        res = await client.get(f"{base_url}{path}", params=query, headers={"X-Emby-Token": api_key})
        res.raise_for_status()
        return res.json()

    async def library_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return {"movies": [], "series": [], "episodes": []}
        proxy = module_proxy("emby")
        async with httpx.AsyncClient(proxy=proxy or None, timeout=30, follow_redirects=True) as client:
            movies_series, episodes = await asyncio.gather(
                self._get(client, base_url, "/Items", api_key, self._snapshot_params("Movie,Series")),
                self._get(client, base_url, "/Items", api_key, self._snapshot_params("Episode")),
            )
        items = movies_series.get("Items", [])
        return {
            "movies": [item for item in items if item.get("Type") == "Movie"],
            "series": [item for item in items if item.get("Type") == "Series"],
            "episodes": episodes.get("Items", []),
        }

    def _snapshot_params(self, item_types: str) -> dict[str, str]:
        return {
            "Recursive": "true",
            "Limit": "10000",
            "Fields": "ProviderIds,OriginalTitle,SortName,SeriesId,SeriesName,ParentId,IndexNumber,ParentIndexNumber",
            "IncludeItemTypes": item_types,
        }
