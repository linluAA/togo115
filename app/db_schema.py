from __future__ import annotations

import sqlite3

from app.db_core import db, hash_password, utc_now
from app.db_schema_migrations import ensure_columns, migrate_schema, table_columns
from app.db_schema_tables import create_schema


def init_db() -> None:
    with db() as conn:
        create_schema(conn)
        migrate_schema(conn)
        _ensure_default_user(conn)


def _ensure_default_user(conn: sqlite3.Connection) -> None:
    user = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
    if user is not None:
        return
    now = utc_now()
    conn.execute(
        "INSERT INTO users (id, username, password_hash, created_at, updated_at) VALUES (1, ?, ?, ?, ?)",
        ("admin", hash_password("admin123"), now, now),
    )


_table_columns = table_columns
_ensure_columns = ensure_columns
_migrate_schema = migrate_schema
