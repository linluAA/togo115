import asyncio
from urllib.parse import parse_qs, urlparse

from app.services import novnc as novnc_service
from app.services.novnc import default_novnc_url
from app.routers import novnc


def test_default_novnc_url_uses_same_origin_proxy(monkeypatch) -> None:
    monkeypatch.delenv("VNC_PASSWORD", raising=False)
    monkeypatch.setattr(novnc_service, "create_novnc_access_token", lambda: "signed-token")

    url = urlparse(default_novnc_url())
    query = parse_qs(url.query)

    assert url.path == "/novnc/vnc.html"
    assert query["autoconnect"] == ["true"]
    assert query["resize"] == ["remote"]
    assert query["path"] == ["api/novnc/websockify/signed-token"]


def test_default_novnc_url_includes_vnc_password(monkeypatch) -> None:
    monkeypatch.setenv("VNC_PASSWORD", "togo 115")
    monkeypatch.setattr(novnc_service, "create_novnc_access_token", lambda: "signed token")

    url = urlparse(default_novnc_url())
    query = parse_qs(url.query)

    assert query["path"] == ["api/novnc/websockify/signed%20token"]
    assert query["password"] == ["togo 115"]


def test_novnc_status_reports_http_and_websocket(monkeypatch) -> None:
    async def fake_vnc():
        return {"ok": True}

    async def fake_http():
        return {"ok": True, "status_code": 200}

    async def fake_websocket():
        return {"ok": False, "error": "closed", "error_type": "ConnectionClosed"}

    async def fake_rfb():
        return {"ok": True, "banner": "RFB 003.008"}

    monkeypatch.setattr(novnc_service, "probe_vnc_tcp", fake_vnc)
    monkeypatch.setattr(novnc_service, "probe_novnc_http", fake_http)
    monkeypatch.setattr(novnc_service, "probe_novnc_websocket", fake_websocket)
    monkeypatch.setattr(novnc_service, "probe_rfb_handshake", fake_rfb)

    payload = asyncio.run(novnc.novnc_status(user={"username": "admin"}))

    assert payload == {
        "ok": False,
        "vnc": {"ok": True},
        "http": {"ok": True, "status_code": 200},
        "websocket": {"ok": False, "error": "closed", "error_type": "ConnectionClosed"},
        "rfb": {"ok": True, "banner": "RFB 003.008"},
        "ports": {"vnc": "5900", "novnc": "6080"},
        "client_path": "api/novnc/websockify",
    }


def test_novnc_websocket_accepts_signed_query_token(monkeypatch) -> None:
    class FakeQueryParams:
        def get(self, key):
            return "signed-token" if key == "novnc_token" else None

    class FakeWebSocket:
        cookies = {}
        query_params = FakeQueryParams()

    monkeypatch.setattr(novnc, "verify_novnc_access_token", lambda token: token == "signed-token")

    assert novnc._websocket_is_authenticated(FakeWebSocket()) is True


def test_novnc_websocket_accepts_signed_path_token(monkeypatch) -> None:
    class FakeQueryParams:
        def get(self, key):
            return None

    class FakeWebSocket:
        cookies = {}
        query_params = FakeQueryParams()

    monkeypatch.setattr(novnc, "verify_novnc_access_token", lambda token: token == "signed-token")

    assert novnc._websocket_is_authenticated(FakeWebSocket(), "signed-token") is True
