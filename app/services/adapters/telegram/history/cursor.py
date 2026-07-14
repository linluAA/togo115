from __future__ import annotations

from app.db import add_log, db, utc_now


class TelegramCursorMixin:
    def _telegram_cursor(self, source: str) -> int:
        try:
            with db() as conn:
                row = conn.execute("SELECT last_message_id FROM telegram_scan_cursors WHERE source = ?", (source,)).fetchone()
            return int(row["last_message_id"] or 0) if row else 0
        except Exception as exc:
            add_log("warning", "telegram", "读取 Telegram 扫描游标失败，降级为普通扫描", {"dialog": source, "error": str(exc)})
            return 0

    def _update_telegram_cursor(self, source: str, message_id: int) -> None:
        if message_id <= 0:
            return
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO telegram_scan_cursors (source, last_message_id, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        last_message_id = MAX(telegram_scan_cursors.last_message_id, excluded.last_message_id),
                        updated_at = excluded.updated_at
                    """,
                    (source, message_id, utc_now()),
                )
        except Exception as exc:
            add_log("warning", "telegram", "更新 Telegram 扫描游标失败", {"dialog": source, "message_id": message_id, "error": str(exc)})

