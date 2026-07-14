from __future__ import annotations

from typing import Any

from app.db import db, json_dumps, json_loads, utc_now


def get_setting(key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except Exception:
        # Tests or partial environments may not have settings initialized yet.
        return default or {}
    return json_loads(row["value"] if row else None, default or {})


def save_setting(key: str, value: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json_dumps(value), utc_now()),
        )


def get_flow(provider: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT payload FROM login_flows WHERE provider = ?", (provider,)).fetchone()
    return json_loads(row["payload"] if row else None, {})


def save_flow(provider: str, payload: dict[str, Any]) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO login_flows (provider, payload, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (provider, json_dumps(payload), now, now),
        )


def module_proxy(module: str) -> str | None:
    proxy = get_setting("proxy")
    modules = proxy.get("modules") or []
    if isinstance(modules, str):
        modules = [x.strip() for x in modules.split(",") if x.strip()]
    return proxy.get("url") if module in modules else None
