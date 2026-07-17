from __future__ import annotations

"""Shared httpx client pool keyed by proxy/timeout/follow_redirects."""

import asyncio
import threading
from typing import Any

import httpx

_lock = threading.RLock()
_clients: dict[tuple[Any, ...], httpx.AsyncClient] = {}
_client_loops: dict[tuple[Any, ...], int] = {}


class SharedAsyncClient:
    """Thin wrapper so existing async-with client code does not close the pool client."""

    __slots__ = ("_client",)

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def __aenter__(self) -> "SharedAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def aclose(self) -> None:
        return None


def shared_async_client(
    *,
    proxy: str | None = None,
    timeout: float | httpx.Timeout = 20,
    follow_redirects: bool = True,
) -> SharedAsyncClient:
    """Return a process/loop-local AsyncClient wrapper, creating it on first use."""
    timeout_key: Any
    if isinstance(timeout, httpx.Timeout):
        timeout_key = (
            timeout.connect,
            timeout.read,
            timeout.write,
            timeout.pool,
        )
    else:
        timeout_key = float(timeout)
    key = (str(proxy or ""), timeout_key, bool(follow_redirects))
    loop_id = id(asyncio.get_running_loop())
    with _lock:
        existing = _clients.get(key)
        if existing is not None and not existing.is_closed and _client_loops.get(key) == loop_id:
            return SharedAsyncClient(existing)
        client = httpx.AsyncClient(
            proxy=proxy or None,
            timeout=timeout,
            follow_redirects=follow_redirects,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16, keepalive_expiry=30),
        )
        _clients[key] = client
        _client_loops[key] = loop_id
        return SharedAsyncClient(client)


async def aclose_shared_clients() -> None:
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
        _client_loops.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
