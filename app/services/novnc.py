from __future__ import annotations

import asyncio
import os
from urllib.parse import urlencode

import httpx
import websockets


def novnc_port() -> str:
    return str(os.getenv("NOVNC_PORT") or "6080").strip() or "6080"


def vnc_port() -> str:
    return str(os.getenv("VNC_PORT") or "5900").strip() or "5900"


def default_novnc_url() -> str:
    params = {
        "autoconnect": "true",
        "resize": "remote",
        "path": "api/novnc/websockify",
    }
    password = str(os.getenv("VNC_PASSWORD") or "").strip()
    if password:
        params["password"] = password
    return f"/novnc/vnc.html?{urlencode(params)}"


def novnc_http_base() -> str:
    return f"http://127.0.0.1:{novnc_port()}"


def novnc_ws_url() -> str:
    return f"ws://127.0.0.1:{novnc_port()}/websockify"


async def novnc_status_payload() -> dict:
    vnc_status = await probe_vnc_tcp()
    http_status = await probe_novnc_http()
    ws_status = await probe_novnc_websocket()
    return {
        "ok": vnc_status["ok"] and http_status["ok"] and ws_status["ok"],
        "vnc": vnc_status,
        "http": http_status,
        "websocket": ws_status,
        "ports": {"vnc": vnc_port(), "novnc": novnc_port()},
        "client_path": "api/novnc/websockify",
    }


async def probe_novnc_http() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.get(f"{novnc_http_base()}/vnc.html")
        return {"ok": response.status_code < 500, "status_code": response.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


async def probe_vnc_tcp() -> dict:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", int(vnc_port())), timeout=5)
        writer.close()
        await writer.wait_closed()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


async def probe_novnc_websocket() -> dict:
    try:
        async with websockets.connect(novnc_ws_url(), subprotocols=["binary"], open_timeout=5, max_size=None):
            return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
