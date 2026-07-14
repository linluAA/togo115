from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx
import websockets
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature
from starlette.websockets import WebSocketDisconnect

from app.auth import current_user, serializer
from app.config import settings
from app.services.novnc import default_novnc_url, novnc_http_base, novnc_port, novnc_ws_url


router = APIRouter()

_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _HOP_BY_HOP_HEADERS}


@router.get("/novnc")
@router.get("/novnc/")
async def novnc_index(user: dict = Depends(current_user)) -> RedirectResponse:
    return RedirectResponse(default_novnc_url())


@router.get("/novnc/{path:path}")
async def novnc_http_proxy(path: str, request: Request, user: dict = Depends(current_user)) -> Response:
    target = f"{novnc_http_base()}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            upstream = await client.get(target)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"noVNC service is not reachable on 127.0.0.1:{novnc_port()}",
        ) from exc

    return Response(
        upstream.content,
        status_code=upstream.status_code,
        headers=_response_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


@router.websocket("/novnc/websockify")
async def novnc_websocket_proxy(websocket: WebSocket) -> None:
    if not _websocket_is_authenticated(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    protocols = _websocket_protocols(websocket)
    try:
        async with websockets.connect(novnc_ws_url(), subprotocols=protocols or None, max_size=None) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)
            await _bridge_websocket(websocket, upstream)
    except OSError:
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


def _websocket_is_authenticated(websocket: WebSocket) -> bool:
    token = websocket.cookies.get(settings.session_cookie)
    if not token:
        return False
    try:
        serializer.loads(token)
    except BadSignature:
        return False
    return True


def _websocket_protocols(websocket: WebSocket) -> list[str]:
    header = websocket.headers.get("sec-websocket-protocol") or ""
    return [item.strip() for item in header.split(",") if item.strip()]


async def _bridge_websocket(websocket: WebSocket, upstream) -> None:
    client_task = asyncio.create_task(_client_to_upstream(websocket, upstream))
    upstream_task = asyncio.create_task(_upstream_to_client(websocket, upstream))
    done, pending = await asyncio.wait({client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


async def _client_to_upstream(websocket: WebSocket, upstream) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                await upstream.close()
                return
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
            elif message.get("text") is not None:
                await upstream.send(message["text"])
    except WebSocketDisconnect:
        await upstream.close()


async def _upstream_to_client(websocket: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)
