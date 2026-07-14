import asyncio

from app.services.novnc import default_novnc_url
from app.services.sources import rss_torznab_hdhive as hdhive
from app.services.sources.rss_torznab_hdhive import _with_hdhive_novnc_url
from app.routers import novnc


def test_default_novnc_url_uses_same_origin_proxy() -> None:
    assert default_novnc_url() == "/novnc/vnc.html?autoconnect=true&resize=remote&path=novnc%2Fwebsockify"


def test_hdhive_login_uses_default_novnc_proxy(monkeypatch) -> None:
    monkeypatch.delenv("TOGO115_NOVNC_URL", raising=False)

    payload = _with_hdhive_novnc_url({}, {"ok": True})

    assert payload["novnc_url"] == default_novnc_url()


def test_hdhive_login_keeps_configured_novnc_url(monkeypatch) -> None:
    monkeypatch.setenv("TOGO115_NOVNC_URL", "https://example.test/vnc.html")

    payload = _with_hdhive_novnc_url({}, {"ok": True})

    assert payload["novnc_url"] == "https://example.test/vnc.html"


def test_hdhive_profile_lock_returns_running_payload(monkeypatch) -> None:
    monkeypatch.delenv("TOGO115_NOVNC_URL", raising=False)

    payload = hdhive._hdhive_login_error(
        RuntimeError("The profile appears to be in use by another Chromium process"),
        "/data/hdhive-browser",
    )

    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["user_data_dir"] == "/data/hdhive-browser"
    assert payload["novnc_url"] == default_novnc_url()


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
    async def fake_http():
        return {"ok": True, "status_code": 200}

    async def fake_websocket():
        return {"ok": False, "error": "closed", "error_type": "ConnectionClosed"}

    monkeypatch.setattr(novnc, "_probe_novnc_http", fake_http)
    monkeypatch.setattr(novnc, "_probe_novnc_websocket", fake_websocket)

    payload = asyncio.run(novnc.novnc_status(user={"username": "admin"}))

    assert payload == {
        "ok": False,
        "http": {"ok": True, "status_code": 200},
        "websocket": {"ok": False, "error": "closed", "error_type": "ConnectionClosed"},
        "port": "6080",
    }
