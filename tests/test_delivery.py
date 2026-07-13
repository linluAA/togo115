import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.db import db, init_db, json_dumps, utc_now
from app.services.integrations import Pan115Adapter
from app.services.subscription_delivery import deliver_resource


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakePan115Client:
    def __init__(self) -> None:
        self.post_payload: dict | None = None

    async def __aenter__(self) -> "FakePan115Client":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, **kwargs) -> FakeResponse:
        if url == Pan115Adapter.USER_NAV_URL:
            return FakeResponse({"data": {"user_id": "115uid"}})
        if url == Pan115Adapter.OFFLINE_SPACE_URL:
            return FakeResponse({"sign": "offline-sign", "time": 123456})
        return FakeResponse({}, 404)

    async def post(self, url: str, data: dict, **kwargs) -> FakeResponse:
        self.post_payload = {"url": url, "data": data, "headers": kwargs.get("headers")}
        return FakeResponse({"state": True})


class DeliveryModeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def _resource(self, url: str, delivery_mode: str = "115") -> int:
        now = utc_now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES ('delivery', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (json_dumps({"mode": delivery_mode}), now),
            )
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path, created_at, updated_at)
                VALUES
                    ('南部档案', 'tv', '[]', '{}', '115', '/电视剧/南部档案', ?, ?)
                """,
                (now, now),
            )
            subscription_id = int(cursor.lastrowid)
            cursor = conn.execute(
                """
                INSERT INTO resources (subscription_id, source, title, url, status, created_at)
                VALUES (?, 'site_plugin:test', '南部档案 第 21 集 1080p', ?, 'pending', ?)
                """,
                (subscription_id, url, now),
            )
            return int(cursor.lastrowid)

    def _resource_status(self, resource_id: int) -> str:
        with db() as conn:
            row = conn.execute("SELECT status FROM resources WHERE id = ?", (resource_id,)).fetchone()
        return str(row["status"])

    async def test_115_delivery_mode_sends_magnet_to_pan115_offline_download(self) -> None:
        resource_id = self._resource("magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        pan = Mock()
        pan.offline_download = AsyncMock(return_value=True)
        pan.transfer = AsyncMock(return_value=True)
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=True)

        with patch("app.services.subscription_delivery.Pan115Adapter", return_value=pan), patch("app.services.subscription_delivery.TelegramBotAdapter", return_value=bot):
            ok = await deliver_resource(resource_id)

        self.assertTrue(ok)
        pan.offline_download.assert_awaited_once_with("magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "/电视剧/南部档案")
        pan.transfer.assert_not_called()
        bot.forward_to_bot.assert_not_called()

    async def test_telegram_delivery_mode_still_sends_magnet_to_bot(self) -> None:
        resource_id = self._resource("magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "telegram_bot")
        pan = Mock()
        pan.offline_download = AsyncMock(return_value=True)
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=True)

        with patch("app.services.subscription_delivery.Pan115Adapter", return_value=pan), patch("app.services.subscription_delivery.TelegramBotAdapter", return_value=bot):
            ok = await deliver_resource(resource_id)

        self.assertTrue(ok)
        bot.forward_to_bot.assert_awaited_once_with("magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        pan.offline_download.assert_not_called()

    async def test_expired_115_link_is_not_delivered_to_any_target(self) -> None:
        resource_id = self._resource("https://115.com/s/expired?password=1111", "telegram_bot")
        pan = Mock()
        pan.share_availability = AsyncMock(return_value="unavailable")
        pan.transfer = AsyncMock(return_value=True)
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=True)

        with patch("app.services.subscription_delivery.Pan115Adapter", return_value=pan), patch("app.services.subscription_delivery.TelegramBotAdapter", return_value=bot):
            ok = await deliver_resource(resource_id)

        self.assertFalse(ok)
        pan.share_availability.assert_awaited_once_with("https://115.com/s/expired?password=1111")
        pan.transfer.assert_not_called()
        bot.forward_to_bot.assert_not_called()
        self.assertEqual(self._resource_status(resource_id), "link_invalid")

    async def test_unknown_115_availability_still_delivers(self) -> None:
        resource_id = self._resource("https://115.com/s/recheck?password=1111", "telegram_bot")
        pan = Mock()
        pan.share_availability = AsyncMock(return_value="unknown")
        pan.transfer = AsyncMock(return_value=True)
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=True)

        with patch("app.services.subscription_delivery.Pan115Adapter", return_value=pan), patch("app.services.subscription_delivery.TelegramBotAdapter", return_value=bot):
            ok = await deliver_resource(resource_id)

        self.assertTrue(ok)
        pan.share_availability.assert_awaited_once_with("https://115.com/s/recheck?password=1111")
        pan.transfer.assert_not_called()
        bot.forward_to_bot.assert_awaited_once_with("https://115.com/s/recheck?password=1111")
        self.assertEqual(self._resource_status(resource_id), "delivered")
        with db() as conn:
            row = conn.execute("SELECT last_error FROM resources WHERE id = ?", (resource_id,)).fetchone()
        self.assertIsNone(row["last_error"])


    def test_delivery_failed_status_classifier(self) -> None:
        from app.services.subscription_delivery_state import _delivery_failed_status

        self.assertEqual(_delivery_failed_status("115 \u5206\u4eab\u6709\u6548\u6027\u5f85\u590d\u68c0\uff0c\u7b49\u5f85\u91cd\u8bd5"), "pending_recheck")
        self.assertEqual(_delivery_failed_status("115 \u5206\u4eab\u94fe\u63a5\u5df2\u5931\u6548"), "link_invalid")
        self.assertEqual(_delivery_failed_status("network timeout"), "delivery_failed_retryable")
        self.assertEqual(_delivery_failed_status("bot rejected"), "delivery_failed_final")

    async def test_duplicate_delivery_link_is_not_forwarded_twice(self) -> None:
        first_id = self._resource("https://115cdn.com/s/swssxf43nbi?password=8888", "telegram_bot")
        second_id = self._resource("https://115.com/s/swssxf43nbi?password=8888", "telegram_bot")
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=True)

        with patch("app.services.subscription_delivery.TelegramBotAdapter", return_value=bot):
            first_ok = await deliver_resource(first_id)
            second_ok = await deliver_resource(second_id)

        self.assertTrue(first_ok)
        self.assertTrue(second_ok)
        bot.forward_to_bot.assert_awaited_once_with("https://115cdn.com/s/swssxf43nbi?password=8888")
        self.assertEqual(self._resource_status(first_id), "delivered")
        self.assertEqual(self._resource_status(second_id), "delivered")


class Pan115OfflineDownloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_offline_download_submits_task_to_configured_target_cid(self) -> None:
        adapter = Pan115Adapter()
        client = FakePan115Client()

        with (
            patch("app.services.integrations.get_setting", return_value={"cookie": "UID=abc;", "target_cid": "888"}),
            patch("app.services.integrations.add_log"),
            patch.object(adapter, "_client", return_value=client),
        ):
            ok = await adapter.offline_download("magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc", "/ignored")

        self.assertTrue(ok)
        self.assertIsNotNone(client.post_payload)
        assert client.post_payload is not None
        self.assertEqual(client.post_payload["url"], Pan115Adapter.OFFLINE_ADD_TASK_URL)
        self.assertEqual(client.post_payload["data"]["url"], "magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc")
        self.assertEqual(client.post_payload["data"]["wp_path_id"], "888")
        self.assertEqual(client.post_payload["data"]["uid"], "115uid")
        self.assertEqual(client.post_payload["data"]["sign"], "offline-sign")
        self.assertEqual(client.post_payload["data"]["time"], "123456")

    async def test_transfer_treats_already_received_as_success(self) -> None:
        adapter = Pan115Adapter()

        self.assertTrue(adapter._transfer_ok({"state": False, "message": "文件已接收，无需重复接收！"}))
        self.assertTrue(adapter._transfer_ok({"errno": 0}))
        self.assertFalse(adapter._transfer_ok({"state": False, "message": "提取码错误"}))


if __name__ == "__main__":
    unittest.main()
