from __future__ import annotations

import httpx

from app.services.integration_state import get_setting, module_proxy
from app.services.http_client import shared_async_client


class EmbyImagesMixin:
    async def image_response(self, item_id: str) -> tuple[bytes, str]:
        return await self._image_response(f"/Items/{item_id}/Images/Primary", 480)

    async def user_image_response(self, user_id: str) -> tuple[bytes, str]:
        return await self._image_response(f"/Users/{user_id}/Images/Primary", 240)

    async def _image_response(self, path: str, max_width: int) -> tuple[bytes, str]:
        config = get_setting("emby")
        api_key = config.get("api_key")
        base_url = self._base_url(config)
        if not base_url or not api_key:
            return b"", "image/jpeg"
        proxy = module_proxy("emby")
        async with shared_async_client(proxy=proxy or None, timeout=20, follow_redirects=True) as client:
            res = await client.get(
                f"{base_url}{path}",
                params={"api_key": api_key, "maxWidth": max_width},
                headers={"X-Emby-Token": api_key},
            )
            res.raise_for_status()
            return res.content, res.headers.get("content-type", "image/jpeg")
