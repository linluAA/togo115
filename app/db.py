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
    # 优化6: 启用 WAL 模式，提升并发读写性能
    conn.execute("PRAGMA journal_mode=WAL")
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
        # 优化6: 创建日志查询索引，加速按级别过滤
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level, id DESC)")
        user = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
        if user is None:
            now = utc_now()
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at, updated_at) VALUES (1, ?, ?, ?, ?)",
                ("admin", hash_password("admin123"), now, now),
            )


def add_log(level: str, scope: str, message: str, payload: dict[str, Any] | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO logs (level, scope, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (level, scope, message, json_dumps(payload) if payload else None, utc_now()),
        )
