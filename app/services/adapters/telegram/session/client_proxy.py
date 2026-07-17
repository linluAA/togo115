from __future__ import annotations

from urllib.parse import urlparse


def telethon_proxy(proxy_url: str | None):
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    if scheme.startswith("socks"):
        return socks_proxy_tuple(parsed, scheme)
    if scheme in ("http", "https"):
        return ("http", parsed.hostname, parsed.port, True, parsed.username, parsed.password)
    return None


def socks_proxy_tuple(parsed, scheme: str):
    try:
        import socks
    except ImportError as exc:
        raise RuntimeError("使用 socks 代理需要安装 PySocks") from exc
    proxy_type = socks.SOCKS5 if scheme == "socks5" else socks.SOCKS4
    return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password)
