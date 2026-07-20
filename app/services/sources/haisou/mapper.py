from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.adapters.pan115 import normalize_115_share_link
from app.services.link.downloads import is_valid_download_link
from app.services.types import SearchResult


def map_haisou_items(
    items: list[dict[str, Any]] | list[Any],
    *,
    source_name: str = "海搜 Haisou",
    source_type: str = "site_plugin",
    platforms: list[str] | None = None,
) -> list[SearchResult]:
    allowed = {str(item).strip().lower() for item in (platforms or ["115"]) if str(item).strip()}
    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        platform = str(raw.get("platform") or "").strip().lower()
        if allowed and platform and platform not in allowed:
            continue
        if platform and platform != "115":
            continue
        url = build_haisou_share_url(raw)
        if not url or not is_valid_download_link(url) or url in seen:
            continue
        seen.add(url)
        title = str(raw.get("title") or "").strip() or source_name
        context_parts = [
            title,
            str(raw.get("platformName") or platform or ""),
            f"size={raw.get('sizeBytes')}" if raw.get("sizeBytes") is not None else "",
            f"files={raw.get('fileCount')}" if raw.get("fileCount") is not None else "",
            f"hsid={raw.get('hsid')}" if raw.get("hsid") else "",
        ]
        context = "\n".join(part for part in context_parts if part)
        results.append(
            SearchResult(
                title=title[:120],
                url=url,
                source=f"{source_type}:{source_name}",
                message_id=str(raw.get("hsid") or raw.get("shareCode") or "") or None,
                context=context,
            )
        )
    return results


def build_haisou_share_url(item: dict[str, Any]) -> str:
    share_url = str(item.get("shareUrl") or item.get("share_url") or "").strip()
    share_code = str(item.get("shareCode") or item.get("share_code") or "").strip()
    share_pwd = str(item.get("sharePwd") or item.get("share_pwd") or item.get("pwd") or "").strip()
    platform = str(item.get("platform") or "").strip().lower()

    if not share_url and platform == "115" and share_code:
        share_url = f"https://115.com/s/{share_code}"
    if not share_url:
        return ""

    if platform == "115" or "115.com" in share_url or "115cdn.com" in share_url:
        return _with_115_password(share_url, share_pwd)
    return share_url


def _with_115_password(link: str, password: str | None) -> str:
    base = normalize_115_share_link(link) or str(link or "").strip()
    if not base:
        return ""
    if not password:
        return base
    parsed = urlparse(base)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    keys = {key.lower() for key, _ in query_items}
    if {"password", "pwd", "receive_code"} & keys:
        return base
    query_items.append(("password", str(password).strip()))
    return urlunparse(parsed._replace(query=urlencode(query_items)))