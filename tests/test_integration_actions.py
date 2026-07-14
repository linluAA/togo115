from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services import integration_actions
from app.services.hdhive_browser import hdhive_playwright_proxy


class IntegrationActionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_actions_delegate_to_adapter(self) -> None:
        adapter = Mock()
        adapter.qr_login_start = AsyncMock(return_value={"url": "tg://login"})
        adapter.send_login_code = AsyncMock(return_value={"phone_code_hash": "hash"})
        adapter.sign_in_code = AsyncMock(return_value={"ok": True})
        adapter.login_status = AsyncMock(return_value={"logged_in": True})
        adapter.dialogs = AsyncMock(return_value=[{"id": 1}])

        with patch.object(integration_actions, "TelegramClientAdapter", Mock(return_value=adapter)):
            qr = await integration_actions.telegram_qr_login_start()
            code = await integration_actions.telegram_send_login_code("+100")
            signed = await integration_actions.telegram_sign_in_code("+100", "12345")
            status = await integration_actions.telegram_login_status()
            dialogs = await integration_actions.telegram_dialogs()

        self.assertEqual(qr, {"url": "tg://login"})
        self.assertEqual(code, {"phone_code_hash": "hash"})
        self.assertEqual(signed, {"ok": True})
        self.assertEqual(status, {"logged_in": True})
        self.assertEqual(dialogs, {"dialogs": [{"id": 1}]})
        adapter.qr_login_start.assert_awaited_once_with()
        adapter.send_login_code.assert_awaited_once_with("+100")
        adapter.sign_in_code.assert_awaited_once_with("+100", "12345")
        adapter.login_status.assert_awaited_once_with()
        adapter.dialogs.assert_awaited_once_with()

    async def test_pan115_actions_delegate_to_adapter(self) -> None:
        adapter = Mock()
        adapter.qr_login_start = AsyncMock(return_value={"uid": "uid"})
        adapter.qrcode_image = AsyncMock(return_value=(b"qr", "image/png"))
        adapter.qr_login_status = AsyncMock(return_value={"logged_in": True})
        adapter.list_folders = AsyncMock(return_value={"items": [{"id": "1"}]})
        adapter.transfer = AsyncMock(return_value=True)

        with patch.object(integration_actions, "Pan115Adapter", Mock(return_value=adapter)):
            qr = await integration_actions.pan115_qr_login_start("web")
            image = await integration_actions.pan115_qrcode_image("uid", "web")
            status = await integration_actions.pan115_login_status()
            folders = await integration_actions.pan115_folders("0")
            saved = await integration_actions.pan115_save_link("https://115.com/s/demo", "/tv")

        self.assertEqual(qr, {"uid": "uid"})
        self.assertEqual(image, (b"qr", "image/png"))
        self.assertEqual(status, {"logged_in": True})
        self.assertEqual(folders, {"items": [{"id": "1"}]})
        self.assertEqual(saved, {"ok": True})
        adapter.qr_login_start.assert_awaited_once_with("web")
        adapter.qrcode_image.assert_awaited_once_with("uid", "web")
        adapter.qr_login_status.assert_awaited_once_with()
        adapter.list_folders.assert_awaited_once_with("0")
        adapter.transfer.assert_awaited_once_with("https://115.com/s/demo", "/tv")

    async def test_hdhive_login_browser_delegates_to_source_helper(self) -> None:
        source = {"plugin": "hdhive", "url": "https://hdhive.com/"}
        with patch.object(integration_actions, "open_hdhive_embedded_browser", AsyncMock(return_value={"ok": True})) as login:
            result = await integration_actions.hdhive_login_browser(source)

        self.assertEqual(result, {"ok": True})
        login.assert_awaited_once_with(source)

    def test_hdhive_browser_uses_source_proxy(self) -> None:
        with patch("app.services.hdhive_browser.get_setting", return_value={"url": "socks5://user:pass@127.0.0.1:7890"}):
            proxy = hdhive_playwright_proxy({"use_proxy": True})

        self.assertEqual(proxy, {"server": "socks5://127.0.0.1:7890", "username": "user", "password": "pass"})

    def test_hdhive_browser_ignores_proxy_when_source_disabled(self) -> None:
        with patch("app.services.hdhive_browser.get_setting", return_value={"url": "http://127.0.0.1:7890"}):
            proxy = hdhive_playwright_proxy({"use_proxy": False})

        self.assertIsNone(proxy)

    async def test_telegram_errors_are_logged_and_reraised(self) -> None:
        adapter = Mock()
        adapter.qr_login_start = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch.object(integration_actions, "TelegramClientAdapter", Mock(return_value=adapter)),
            patch.object(integration_actions, "add_log") as add_log,
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await integration_actions.telegram_qr_login_start()

        add_log.assert_called_once_with("error", "telegram", "Telegram 扫码登录创建失败", {"error": "boom"})

    async def test_pan115_errors_are_logged_and_reraised(self) -> None:
        adapter = Mock()
        adapter.list_folders = AsyncMock(side_effect=RuntimeError("cookie missing"))

        with (
            patch.object(integration_actions, "Pan115Adapter", Mock(return_value=adapter)),
            patch.object(integration_actions, "add_log") as add_log,
        ):
            with self.assertRaisesRegex(RuntimeError, "cookie missing"):
                await integration_actions.pan115_folders("123")

        add_log.assert_called_once_with(
            "error",
            "115",
            "115 目录列表获取失败",
            {"error": "cookie missing", "cid": "123"},
        )
