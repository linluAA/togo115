from __future__ import annotations

from typing import Any

from app.db import db, row_to_dict


def list_logs(
    *,
    mode: str = "simple",
    limit: int = 100,
    before_id: int | None = None,
    after_id: int | None = None,
) -> list[dict]:
    limit = max(1, min(int(limit or 100), 300))
    levels = ("info", "warning", "error") if mode != "debug" else ("debug", "info", "warning", "error")
    placeholders = ",".join("?" for _ in levels)
    where = [f"level IN ({placeholders})"]
    params: list[Any] = list(levels)
    if before_id:
        where.append("id < ?")
        params.append(before_id)
    if after_id:
        where.append("id > ?")
        params.append(after_id)
    params.append(limit)
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM logs WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", params).fetchall()
    return [row_to_dict(row) or {} for row in rows]
