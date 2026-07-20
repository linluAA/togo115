from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.adapters.pan115_share import (
    SHARE_AUTH_REQUIRED,
    SHARE_AVAILABLE,
    SHARE_RATE_LIMITED,
    SHARE_UNAVAILABLE,
    SHARE_UNKNOWN,
    classify_share_payload,
    clear_share_availability_cache,
    probe_share_availability,
)
from app.services.adapters.pan115 import Pan115Adapter, normalize_115_share_link


class FakeResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, *args, **kwargs) -> FakeResponse:
        self.calls += 1
        return self.response


class Pan115ShareClassificationTest(unittest.TestCase):
    def test_available_by_state(self) -> None:
        info = classify_share_payload({"state": True, "data": {"list": [{"n": "a"}]}})
        self.assertEqual(info.status, SHARE_AVAILABLE)
        self.assertEqual(info.reason, "ok")

    def test_expired_message(self) -> None:
        info = classify_share_payload({"state": False, "message": "文件不存在或已过期"})
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "expired")

    def test_password_error_message(self) -> None:
        info = classify_share_payload({"state": False, "msg": "提取码错误"})
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "password_error")

    def test_cancelled_message(self) -> None:
        info = classify_share_payload({"state": False, "error": "分享已取消"})
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "cancelled")

    def test_auth_required_message(self) -> None:
        info = classify_share_payload({"state": False, "message": "请先登录", "errno": 99})
        self.assertEqual(info.status, SHARE_AUTH_REQUIRED)
        self.assertEqual(info.reason, "cookie_invalid")

    def test_rate_limited_message(self) -> None:
        info = classify_share_payload({"state": False, "message": "操作过于频繁", "errno": 911})
        self.assertEqual(info.status, SHARE_RATE_LIMITED)
        self.assertEqual(info.reason, "rate_limited")

    def test_legacy_mapping(self) -> None:
        self.assertEqual(classify_share_payload({"state": True}).legacy_status, SHARE_AVAILABLE)
        self.assertEqual(classify_share_payload({"state": False, "message": "已过期"}).legacy_status, SHARE_UNAVAILABLE)
        self.assertEqual(classify_share_payload({"state": False, "message": "请先登录"}).legacy_status, SHARE_UNKNOWN)


class Pan115ShareProbeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_share_availability_cache()

    async def test_cookie_missing_is_auth_required_not_available(self) -> None:
        info = await probe_share_availability(
            link="https://115.com/s/abc?password=1111",
            share_code="abc",
            receive_code="1111",
            cookie=None,
            client_factory=lambda: FakeClient(FakeResponse({"state": True})),
            normalize_link=normalize_115_share_link,
        )
        self.assertEqual(info.status, SHARE_AUTH_REQUIRED)
        self.assertEqual(info.reason, "cookie_missing")
        self.assertEqual(info.legacy_status, SHARE_UNKNOWN)

    async def test_probe_uses_cache(self) -> None:
        client = FakeClient(FakeResponse({"state": True, "data": {"list": [{"n": "ep01"}]}}))

        first = await probe_share_availability(
            link="https://115.com/s/abc?password=1111",
            share_code="abc",
            receive_code="1111",
            cookie="UID=1",
            client_factory=lambda: client,
            normalize_link=normalize_115_share_link,
        )
        second = await probe_share_availability(
            link="https://115.com/s/abc?password=1111",
            share_code="abc",
            receive_code="1111",
            cookie="UID=1",
            client_factory=lambda: client,
            normalize_link=normalize_115_share_link,
        )
        self.assertEqual(first.status, SHARE_AVAILABLE)
        self.assertFalse(first.cached)
        self.assertEqual(second.status, SHARE_AVAILABLE)
        self.assertTrue(second.cached)
        self.assertEqual(client.calls, 1)

    async def test_http_404_is_unavailable(self) -> None:
        client = FakeClient(FakeResponse({}, status_code=404))
        info = await probe_share_availability(
            link="https://115.com/s/missing?password=1111",
            share_code="missing",
            receive_code="1111",
            cookie="UID=1",
            client_factory=lambda: client,
            normalize_link=normalize_115_share_link,
        )
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "not_found")

    async def test_adapter_legacy_share_availability_maps_auth_to_unknown(self) -> None:
        adapter = Pan115Adapter()
        with patch.object(adapter, "inspect_share", AsyncMock(return_value=classify_share_payload({"state": False, "message": "请先登录"}))):
            # inspect_share patched; share_availability should map via legacy
            pass
        from app.services.adapters.pan115_share import ShareAvailability

        with patch.object(
            adapter,
            "inspect_share",
            AsyncMock(return_value=ShareAvailability(SHARE_AUTH_REQUIRED, "cookie_missing")),
        ):
            self.assertEqual(await adapter.share_availability("https://115.com/s/a"), SHARE_UNKNOWN)



class HaisouValidateClassifyTest(unittest.TestCase):
    def test_valid_result(self) -> None:
        from app.services.adapters.pan115_share_haisou import classify_haisou_validate_result

        info = classify_haisou_validate_result({"valid": True, "status": "valid", "reason": "该分享有效"})
        self.assertEqual(info.status, SHARE_AVAILABLE)
        self.assertEqual(info.reason, "haisou_valid")

    def test_expired_result(self) -> None:
        from app.services.adapters.pan115_share_haisou import classify_haisou_validate_result

        info = classify_haisou_validate_result({"valid": False, "status": "expired", "reason": "分享已过期"})
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "expired")


class HaisouShareFallbackProbeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_share_availability_cache()

    async def test_cookie_missing_fallback_available(self) -> None:
        with patch(
            "app.services.adapters.pan115_share._fallback_with_haisou",
            new=AsyncMock(return_value=__import__("app.services.adapters.pan115_share_status", fromlist=["ShareAvailability"]).ShareAvailability(SHARE_AVAILABLE, "haisou_valid", message="ok")),
        ) as fallback:
            info = await probe_share_availability(
                link="https://115.com/s/fb1?password=1111",
                share_code="fb1",
                receive_code="1111",
                cookie=None,
                client_factory=lambda: FakeClient(FakeResponse({"state": True})),
                normalize_link=normalize_115_share_link,
            )
        self.assertEqual(info.status, SHARE_AVAILABLE)
        self.assertEqual(info.reason, "haisou_valid")
        fallback.assert_awaited()

    async def test_cookie_invalid_fallback_available(self) -> None:
        client = FakeClient(FakeResponse({"state": False, "message": "请先登录", "errno": 99}))
        with patch(
            "app.services.adapters.pan115_share._fallback_with_haisou",
            new=AsyncMock(return_value=__import__("app.services.adapters.pan115_share_status", fromlist=["ShareAvailability"]).ShareAvailability(SHARE_AVAILABLE, "haisou_valid")),
        ) as fallback:
            info = await probe_share_availability(
                link="https://115.com/s/fb2?password=2222",
                share_code="fb2",
                receive_code="2222",
                cookie="UID=1",
                client_factory=lambda: client,
                normalize_link=normalize_115_share_link,
            )
        self.assertEqual(info.status, SHARE_AVAILABLE)
        self.assertEqual(info.reason, "haisou_valid")
        fallback.assert_awaited()

    async def test_cookie_missing_without_fallback_keeps_auth_required(self) -> None:
        with patch("app.services.adapters.pan115_share._fallback_with_haisou", new=AsyncMock(return_value=None)):
            info = await probe_share_availability(
                link="https://115.com/s/fb3?password=3333",
                share_code="fb3",
                receive_code="3333",
                cookie=None,
                client_factory=lambda: FakeClient(FakeResponse({"state": True})),
                normalize_link=normalize_115_share_link,
            )
        self.assertEqual(info.status, SHARE_AUTH_REQUIRED)
        self.assertEqual(info.reason, "cookie_missing")

    async def test_try_haisou_fallback_calls_validate(self) -> None:
        from app.services.adapters.pan115_share_haisou import try_haisou_share_fallback

        with patch("app.services.sources.haisou.haisou_enabled", return_value=True), patch(
            "app.services.sources.haisou.HaisouClient"
        ) as client_cls:
            client_cls.return_value.validate = AsyncMock(
                return_value={"valid": False, "status": "invalid", "reason": "分享不存在"}
            )
            info = await try_haisou_share_fallback(
                link="https://115.com/s/x?password=ab",
                receive_code="ab",
                trigger="cookie_missing",
            )
        self.assertIsNotNone(info)
        self.assertEqual(info.status, SHARE_UNAVAILABLE)
        self.assertEqual(info.reason, "not_found")


if __name__ == "__main__":
    unittest.main()
