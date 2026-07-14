from app.services.novnc import default_novnc_url
from app.services.sources.rss_torznab_hdhive import _with_hdhive_novnc_url


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
