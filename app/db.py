import json
import base64
import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import settings

PASSWORD_PREFIX = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "$".join(
        [
            PASSWORD_PREFIX,
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        prefix, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if prefix != PASSWORD_PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def get_connection() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                media_type TEXT NOT NULL CHECK (media_type IN ('tv', 'movie')),
                tmdb_id INTEGER,
                poster_url TEXT,
                overview TEXT,
                release_year INTEGER,
                keywords TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                delivery_mode TEXT NOT NULL DEFAULT '115',
                target_path TEXT,
                emby_count INTEGER NOT NULL DEFAULT 0,
                tmdb_total_count INTEGER NOT NULL DEFAULT 0,
                in_library INTEGER NOT NULL DEFAULT 0,
                last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                message_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                scope TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS login_flows (
                provider TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        _migrate_schema(conn)
        user = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
        if user is None:
            now = utc_now()
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at, updated_at) VALUES (1, ?, ?, ?, ?)",
                ("admin", hash_password("admin123"), now, now),
            )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _ensure_columns(
        conn,
        "subscriptions",
        {
            "title": "TEXT NOT NULL DEFAULT ''",
            "media_type": "TEXT NOT NULL DEFAULT 'tv'",
            "tmdb_id": "INTEGER",
            "poster_url": "TEXT",
            "overview": "TEXT",
            "release_year": "INTEGER",
            "keywords": "TEXT NOT NULL DEFAULT '[]'",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "delivery_mode": "TEXT NOT NULL DEFAULT '115'",
            "target_path": "TEXT",
            "emby_count": "INTEGER NOT NULL DEFAULT 0",
            "tmdb_total_count": "INTEGER NOT NULL DEFAULT 0",
            "tmdb_seasons": "TEXT NOT NULL DEFAULT '[]'",
            "emby_episode_keys": "TEXT NOT NULL DEFAULT '[]'",
            "in_library": "INTEGER NOT NULL DEFAULT 0",
            "completed_at": "TEXT",
            "last_checked_at": "TEXT",
        },
    )
    conn.execute(
        """
        UPDATE resources
        SET subscription_id = (
            SELECT MIN(s2.id)
            FROM subscriptions s2
            JOIN subscriptions s1
              ON s1.media_type = s2.media_type
             AND s1.tmdb_id = s2.tmdb_id
            WHERE s1.id = resources.subscription_id
              AND s1.tmdb_id IS NOT NULL
        )
        WHERE subscription_id IN (
            SELECT s1.id
            FROM subscriptions s1
            JOIN subscriptions s2
              ON s1.media_type = s2.media_type
             AND s1.tmdb_id = s2.tmdb_id
             AND s2.id < s1.id
            WHERE s1.tmdb_id IS NOT NULL
        )
        """
    )
    conn.execute(
        """
        DELETE FROM subscriptions
        WHERE tmdb_id IS NOT NULL
          AND id NOT IN (
              SELECT MIN(id)
              FROM subscriptions
              WHERE tmdb_id IS NOT NULL
              GROUP BY media_type, tmdb_id
          )
        """
    )
    conn.execute(
        """
        DELETE FROM resources
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM resources
            GROUP BY subscription_id, url
        )
        """
    )
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_tmdb_unique
            ON subscriptions(media_type, tmdb_id)
            WHERE tmdb_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_subscriptions_status
            ON subscriptions(status);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_media_title
            ON subscriptions(media_type, title);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_subscription_url
            ON resources(subscription_id, url);
        CREATE INDEX IF NOT EXISTS idx_resources_status
            ON resources(status);
        CREATE INDEX IF NOT EXISTS idx_logs_created_at
            ON logs(created_at);
        """
    )


def add_log(level: str, scope: str, message: str, payload: dict[str, Any] | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (level, scope, message, json_dumps(payload) if payload else None, utc_now()),
        )
        conn.execute(
            """
            DELETE FROM logs
            WHERE id NOT IN (
                SELECT id FROM logs ORDER BY id DESC LIMIT 5000
            )
            """
        )
