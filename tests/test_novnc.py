import asyncio
from urllib.parse import parse_qs, unquote, urlparse

from app.services import novnc as novnc_service
from app.services.novnc import default_novnc_url
from app.services.sources import rss_torznab_hdhive as hdhive
from app.services.sources.rss_torznab_hdhive import _with_hdhive_novnc_url
from app.routers import novnc


def test_default_novnc_url_uses_same_origin_proxy(monkeypatch) -> None:
    monkeypatch.delenv("VNC_PASSWORD", raising=False)
    monkeypatch.setattr(novnc_service, "create_novnc_access_token", lambda: "signed-token")

    url = urlparse(default_novnc_url())
    query = parse_qs(url.query)

    assert url.path == "/novnc/vnc.html"
    assert query["autoconnect"] == ["true"]
    assert query["resize"] == ["remote"]
    assert query["path"] == ["api/novnc/websockify?novnc_token=signed-token"]


def test_default_novnc_url_includes_vnc_password(monkeypatch) -> None:
    monkeypatch.setenv("VNC_PASSWORD", "togo 115")
    monkeypatch.setattr(novnc_service, "create_novnc_access_token", lambda: "signed token")

    url = urlparse(default_novnc_url())
    query = parse_qs(url.query)

    assert query["path"] == ["api/novnc/websockify?novnc_token=signed%20token"]
    assert unquote(query["path"][0]) == "api/novnc/websockify?novnc_token=signed token"
    assert query["password"] == ["togo 115"]


def test_hdhive_login_uses_default_novnc_proxy(monkeypatch) -> None:
    monkeypatch.delenv("TOGO115_NOVNC_URL", raising=False)
    monkeypatch.delenv("VNC_PASSWORD", raising=False)
    monkeypatch.setattr(hdhive, "default_novnc_url", lambda: "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token")

    payload = _with_hdhive_novnc_url({}, {"ok": True})

    assert payload["novnc_url"] == "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token"


def test_hdhive_login_keeps_configured_novnc_url(monkeypatch) -> None:
    monkeypatch.setenv("TOGO115_NOVNC_URL", "https://example.test/vnc.html")

    payload = _with_hdhive_novnc_url({}, {"ok": True})

    assert payload["novnc_url"] == "https://example.test/vnc.html"


def test_hdhive_profile_lock_returns_running_payload(monkeypatch) -> None:
    monkeypatch.delenv("TOGO115_NOVNC_URL", raising=False)
    monkeypatch.setattr(hdhive, "default_novnc_url", lambda: "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token")

    payload = hdhive._hdhive_login_error(
        RuntimeError("The profile appears to be in use by another Chromium process"),
        "/data/hdhive-browser",
    )

    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["user_data_dir"] == "/data/hdhive-browser"
    assert payload["novnc_url"] == "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token"


def test_hdhive_login_running_task_logs_brief_status(monkeypatch) -> None:
    logs = []

    class RunningTask:
        def done(self):
            return False

    monkeypatch.setattr(hdhive, "_hdhive_login_browser_task", RunningTask())
    monkeypatch.setattr(hdhive, "add_log", lambda *args: logs.append(args))
    monkeypatch.setattr(hdhive, "default_novnc_url", lambda: "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token")
    monkeypatch.delenv("TOGO115_NOVNC_URL", raising=False)

    payload = asyncio.run(hdhive.start_hdhive_login_browser({"plugin": "hdhive"}))

    assert payload["ok"] is True
    assert payload["queued"] is False
    assert payload["novnc_url"] == "/novnc/vnc.html?path=api%2Fnovnc%2Fwebsockify%3Fnovnc_token%3Dsigned-token"
    assert logs == [("info", "rss", "HDHive login browser is already running", {})]


def test_hdhive_clears_stale_profile_lock(tmp_path, monkeypatch) -> None:
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        (tmp_path / name).write_text("host-12345", encoding="utf-8")
    monkeypatch.setattr(hdhive, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(hdhive, "add_log", lambda *args, **kwargs: None)

    removed = hdhive._clear_stale_hdhive_profile_lock(str(tmp_path))

    assert removed is True
    assert not (tmp_path / "SingletonLock").exists()
    assert not (tmp_path / "SingletonSocket").exists()
    assert not (tmp_path / "SingletonCookie").exists()


def test_hdhive_keeps_live_profile_lock(tmp_path, monkeypatch) -> None:
    (tmp_path / "SingletonLock").write_text("host-12345", encoding="utf-8")
    monkeypatch.setattr(hdhive, "_process_is_alive", lambda pid: True)

    removed = hdhive._clear_stale_hdhive_profile_lock(str(tmp_path))

    assert removed is False
    assert (tmp_path / "SingletonLock").exists()


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
