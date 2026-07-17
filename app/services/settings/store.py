from __future__ import annotations

from typing import Any

from app.db import add_log, db, json_dumps, json_loads, utc_now
from app.services.settings.backup_import import _upsert_setting, _upsert_subscription
from app.services.settings.backup_rows import _serialize_subscription


def list_settings() -> dict[str, dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT key, value, updated_at FROM settings").fetchall()
    return {row["key"]: {"value": json_loads(row["value"], {}), "updated_at": row["updated_at"]} for row in rows}


def save_setting(key: str, value: Any) -> dict[str, bool]:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json_dumps(value), utc_now()),
        )
    add_log("info", "settings", "配置已保存", {"key": key})
    return {"ok": True}


def export_backup() -> dict[str, Any]:
    with db() as conn:
        settings_rows = conn.execute("SELECT key, value, updated_at FROM settings").fetchall()
        subscription_rows = conn.execute("SELECT * FROM subscriptions ORDER BY id").fetchall()
    return {
        "version": 1,
        "exported_at": utc_now(),
        "settings": {row["key"]: json_loads(row["value"], {}) for row in settings_rows},
        "subscriptions": [_serialize_subscription(row) for row in subscription_rows],
    }


def import_backup(payload: dict[str, Any]) -> dict[str, Any]:
    settings_payload = payload.get("settings") if isinstance(payload, dict) else {}
    subscriptions_payload = payload.get("subscriptions") if isinstance(payload, dict) else []
    if not isinstance(settings_payload, dict) or not isinstance(subscriptions_payload, list):
        return {"ok": False, "error": "备份格式错误"}

    now = utc_now()
    imported_settings = 0
    imported_subscriptions = 0
    with db() as conn:
        for key, value in settings_payload.items():
            _upsert_setting(conn, str(key), value if isinstance(value, dict) else {}, now)
            imported_settings += 1
        for item in subscriptions_payload:
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            _upsert_subscription(conn, item, now)
            imported_subscriptions += 1

    add_log("warning", "backup", "配置备份已导入", {"settings": imported_settings, "subscriptions": imported_subscriptions})
    return {"ok": True, "settings": imported_settings, "subscriptions": imported_subscriptions}

