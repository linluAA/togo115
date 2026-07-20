from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.db import add_log
from app.services.adapters.media_emby_dashboard import EmbyDashboardMixin
from app.services.adapters.media_emby_images import EmbyImagesMixin
from app.services.integration_state import get_setting, module_proxy
from app.services.http_client import shared_async_client

EMBY_HTTP_TIMEOUT_SECONDS = 45.0
EMBY_PAGE_SIZE = 1000
EMBY_GET_RETRIES = 3
EMBY_GET_RETRY_DELAY_SECONDS = 0.4


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
        last_error: Exception | None = None
        for attempt in range(1, EMBY_GET_RETRIES + 1):
            try:
                res = await client.get(
                    f"{base_url}{path}",
                    params=query,
                    headers={"X-Emby-Token": api_key},
                )
                res.raise_for_status()
                return res.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = int(getattr(exc.response, "status_code", 0) or 0)
                # Retry only transient server/gateway failures.
                if status and status < 500 and status != 429:
                    raise
            if attempt < EMBY_GET_RETRIES:
                await asyncio.sleep(EMBY_GET_RETRY_DELAY_SECONDS * attempt)
        assert last_error is not None
        raise last_error

    async def library_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return {"movies": [], "series": [], "episodes": []}
        proxy = module_proxy("emby")
        async with shared_async_client(
            proxy=proxy or None,
            timeout=EMBY_HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            # Fetch catalog and episodes independently so one slow path does not always
            # discard everything when the outer waiter is tight.
            movies_series_task = asyncio.create_task(
                self._get_items(client, base_url, api_key, self._snapshot_params("Movie,Series"))
            )
            episodes_task = asyncio.create_task(
                self._get_items(client, base_url, api_key, self._snapshot_params("Episode"))
            )
            items_result, episodes_result = await asyncio.gather(
                movies_series_task,
                episodes_task,
                return_exceptions=True,
            )

        movies: list[dict[str, Any]] = []
        series: list[dict[str, Any]] = []
        episodes: list[dict[str, Any]] = []
        errors: list[str] = []

        if isinstance(items_result, Exception):
            errors.append(f"movies_series:{type(items_result).__name__}:{items_result}")
        else:
            movies = [item for item in items_result if item.get("Type") == "Movie"]
            series = [item for item in items_result if item.get("Type") == "Series"]

        if isinstance(episodes_result, Exception):
            errors.append(f"episodes:{type(episodes_result).__name__}:{episodes_result}")
        else:
            episodes = list(episodes_result or [])

        if errors and not movies and not series and not episodes:
            # Total failure: bubble up so caller can keep stale cache / mark failed.
            raise RuntimeError("; ".join(errors))

        if errors:
            add_log(
                "warning",
                "emby",
                "Emby 快照部分失败，已返回可用部分",
                {
                    "errors": errors[:4],
                    "movies": len(movies),
                    "series": len(series),
                    "episodes": len(episodes),
                },
            )
        return {"movies": movies, "series": series, "episodes": episodes}

    async def _get_items(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        limit = int(params.get("Limit") or EMBY_PAGE_SIZE)
        start = 0
        items: list[dict[str, Any]] = []
        pages = 0
        while True:
            page_params = {**params, "StartIndex": str(start), "Limit": str(limit)}
            page = await self._get(client, base_url, "/Items", api_key, page_params)
            page_items = page.get("Items", []) if isinstance(page, dict) else []
            if not page_items:
                break
            items.extend(page_items)
            pages += 1
            start += len(page_items)
            total = self._total_record_count(page)
            if total is not None and start >= total:
                break
            if total is None and len(page_items) < limit:
                break
            # Soft cap to avoid unbounded runaway on bad TotalRecordCount.
            if pages >= 200 or start >= 200_000:
                add_log(
                    "warning",
                    "emby",
                    "Emby 分页达到保护上限，已截断",
                    {"include": params.get("IncludeItemTypes"), "fetched": len(items), "pages": pages},
                )
                break
        return items

    def _total_record_count(self, page: dict[str, Any]) -> int | None:
        try:
            value = page.get("TotalRecordCount")
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _snapshot_params(self, item_types: str) -> dict[str, str]:
        # Keep fields minimal for faster large-library paging.
        return {
            "Recursive": "true",
            "Limit": str(EMBY_PAGE_SIZE),
            "EnableTotalRecordCount": "true",
            "Fields": "ProviderIds,OriginalTitle,SortName,SeriesId,SeriesName,ParentId,IndexNumber,ParentIndexNumber",
            "IncludeItemTypes": item_types,
        }
