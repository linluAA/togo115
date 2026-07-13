from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services import media_catalog


class MediaCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def test_tmdb_functions_delegate_to_adapter(self) -> None:
        adapter = Mock()
        adapter.trending = AsyncMock(return_value={"tv": [{"id": 1}], "movie": []})
        adapter.search = AsyncMock(return_value=[{"id": 2}])
        adapter.detail = AsyncMock(return_value={"id": 3})

        with patch.object(media_catalog, "TmdbAdapter", Mock(return_value=adapter)):
            trending = await media_catalog.tmdb_trending(limit=30)
            search = await media_catalog.tmdb_search("Drama", "tv")
            detail = await media_catalog.tmdb_detail("tv", 3)

        self.assertEqual(trending, {"tv": [{"id": 1}], "movie": []})
        self.assertEqual(search, {"results": [{"id": 2}]})
        self.assertEqual(detail, {"id": 3})
        adapter.trending.assert_awaited_once_with(limit=30)
        adapter.search.assert_awaited_once_with("Drama", "tv")
        adapter.detail.assert_awaited_once_with("tv", 3)

    async def test_emby_functions_delegate_to_adapter(self) -> None:
        adapter = Mock()
        adapter.dashboard = AsyncMock(return_value={"media_count": 2})
        adapter.image_response = AsyncMock(return_value=(b"image", "image/jpeg"))
        adapter.user_image_response = AsyncMock(return_value=(b"user", "image/png"))

        with patch.object(media_catalog, "EmbyAdapter", Mock(return_value=adapter)):
            dashboard = await media_catalog.emby_dashboard()
            image = await media_catalog.emby_image("item-1")
            user_image = await media_catalog.emby_user_image("user-1")

        self.assertEqual(dashboard, {"media_count": 2})
        self.assertEqual(image, (b"image", "image/jpeg"))
        self.assertEqual(user_image, (b"user", "image/png"))
        adapter.dashboard.assert_awaited_once_with()
        adapter.image_response.assert_awaited_once_with("item-1")
        adapter.user_image_response.assert_awaited_once_with("user-1")
