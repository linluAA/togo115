from __future__ import annotations

import os
from urllib.parse import urlencode


def novnc_port() -> str:
    return str(os.getenv("NOVNC_PORT") or "6080").strip() or "6080"


def vnc_port() -> str:
    return str(os.getenv("VNC_PORT") or "5900").strip() or "5900"


def default_novnc_url() -> str:
    params = {
        "autoconnect": "true",
        "resize": "remote",
        "path": "novnc/websockify",
    }
    password = str(os.getenv("VNC_PASSWORD") or "").strip()
    if password:
        params["password"] = password
    return f"/novnc/vnc.html?{urlencode(params)}"


def novnc_http_base() -> str:
    return f"http://127.0.0.1:{novnc_port()}"


def novnc_ws_url() -> str:
    return f"ws://127.0.0.1:{novnc_port()}/websockify"
