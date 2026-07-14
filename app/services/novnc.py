from __future__ import annotations

import os


def novnc_port() -> str:
    return str(os.getenv("NOVNC_PORT") or "6080").strip() or "6080"


def default_novnc_url() -> str:
    return "/novnc/vnc.html?autoconnect=true&resize=remote&path=novnc%2Fwebsockify"


def novnc_http_base() -> str:
    return f"http://127.0.0.1:{novnc_port()}"


def novnc_ws_url() -> str:
    return f"ws://127.0.0.1:{novnc_port()}/websockify"
