from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.adapters.media_emby import EmbyAdapter
from app.services.subscription.library import snapshot as snapshot_mod
from app.services.subscription.library.snapshot import (
    EMBY_SNAPSHOT_FAILED,
    library_snapshot_or_none,
    reset_library_snapshot_cache,
)


class EmbySnapshotResilienceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_library_snapshot_cache()

    def tearDown(self) -> None:
        reset_library_snapshot_cache()

    async def test_partial_episode_failure_still_returns_movies_series(self) -> None:
        adapter = EmbyAdapter()

        async def fake_get_items(client, base_url, api_key, params):
            types = params.get("IncludeItemTypes")
            if types == "Movie,Series":
                return [
                    {"Id": "m1", "Type": "Movie"},
                    {"Id": "s1", "Type": "Series"},
                ]
            raise httpx_timeout()

        def httpx_timeout():
            import httpx

            return httpx.ReadTimeout("slow")

        with (
            patch("app.services.adapters.media_emby.get_setting", return_value={"server_url": "http://emby", "api_key": "k"}),
            patch("app.services.adapters.media_emby.module_proxy", return_value=None),
            patch.object(adapter, "_get_items", side_effect=fake_get_items),
        ):
            snap = await adapter.library_snapshot()
        self.assertEqual(len(snap["movies"]), 1)
        self.assertEqual(len(snap["series"]), 1)
        self.assertEqual(snap["episodes"], [])

    async def test_get_retries_transient_errors(self) -> None:
        adapter = EmbyAdapter()
        import httpx

        calls = {"n": 0}

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"Items": [], "TotalRecordCount": 0}

        class FakeClient:
            async def get(self, *args, **kwargs):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise httpx.ConnectError("boom")
                return FakeResp()

        result = await adapter._get(FakeClient(), "http://emby", "/Items", "key", {"Limit": "10"})
        self.assertEqual(result, {"Items": [], "TotalRecordCount": 0})
        self.assertEqual(calls["n"], 3)

    async def test_stale_cache_used_when_refresh_fails(self) -> None:
        import time

        good = {"movies": [{"Id": "1", "Type": "Movie"}], "series": [], "episodes": []}
        # Expired past fresh TTL but still inside stale window.
        snapshot_mod._emby_snapshot_cache = (time.time() - snapshot_mod.EMBY_SNAPSHOT_CACHE_TTL_SECONDS - 10, good)
        with (
            patch.object(snapshot_mod, "_emby_configured", return_value=True),
            patch("app.services.subscription.library.snapshot.EmbyAdapter") as cls,
        ):
            cls.return_value.library_snapshot = AsyncMock(side_effect=RuntimeError("down"))
            result = await library_snapshot_or_none(force=True)
        self.assertEqual(result, good)
        self.assertIsNot(result, EMBY_SNAPSHOT_FAILED)

    async def test_fresh_cache_hit_skips_network(self) -> None:
        import time

        good = {"movies": [], "series": [{"Id": "s"}], "episodes": [{"Id": "e"}]}
        snapshot_mod._emby_snapshot_cache = (time.time(), good)
        with (
            patch.object(snapshot_mod, "_emby_configured", return_value=True),
            patch("app.services.subscription.library.snapshot.EmbyAdapter") as cls,
        ):
            cls.return_value.library_snapshot = AsyncMock(side_effect=AssertionError("should not call"))
            result = await library_snapshot_or_none(force=False)
        self.assertEqual(result, good)

    async def test_failed_without_cache_returns_failed_marker(self) -> None:
        with (
            patch.object(snapshot_mod, "_emby_configured", return_value=True),
            patch("app.services.subscription.library.snapshot.EmbyAdapter") as cls,
        ):
            cls.return_value.library_snapshot = AsyncMock(side_effect=RuntimeError("down"))
            result = await library_snapshot_or_none(force=True)
        self.assertIn("__failed__", result)


if __name__ == "__main__":
    unittest.main()
