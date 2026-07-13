from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.db import row_to_dict
from app.services.adapters.pan115 import PAN115_URL_RE, normalize_115_share_link, parse_115_share_link

MAGNET_BTIH_RE = re.compile(r"(?i)(?:xt=urn:btih:|btih:)([a-z0-9]{32,40})")


def canonical_115_url(url: str) -> str:
    value = normalize_115_share_link(str(url or ""))
    if not value or not PAN115_URL_RE.match(value):
        return url
    share_code, receive_code = parse_115_share_link(value)
    if not share_code:
        return url
    return f"https://115.com/s/{share_code}?password={receive_code}" if receive_code else f"https://115.com/s/{share_code}"


def resource_dedupe_key(url: str) -> tuple[str, str] | None:
    value = str(url or "").strip()
    if not value:
        return None
    magnet = MAGNET_BTIH_RE.search(value)
    if magnet:
        return ("magnet", magnet.group(1).lower())
    clean_115 = normalize_115_share_link(value)
    if clean_115 and PAN115_URL_RE.match(clean_115):
        return ("115", canonical_115_url(clean_115))
    return ("url", value) if value else None


def resource_status_is_effective(status: str | None) -> bool:
    return str(status or "pending").casefold() not in {"failed", "pending_recheck", "skipped"}


def existing_resource_rows(conn: sqlite3.Connection, subscription_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT title, url, status FROM resources WHERE subscription_id = ? ORDER BY rowid DESC",
        (subscription_id,),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]
