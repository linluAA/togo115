import json
import base64
import hashlib
import hmac
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, TypeVar

from app.config import settings

PASSWORD_PREFIX = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
SQLITE_CONNECT_TIMEOUT_SECONDS = 3.0
SQLITE_BUSY_TIMEOUT_MS = 3000
SQLITE_LOCK_RETRIES = 3
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.05
_db_lock = threading.RLock()
_wal_initialized_paths: set[str] = set()
_analyze_initialized_paths: set[str] = set()
_T = TypeVar("_T")

# Reused per-thread SQLite connection: opening a connection and replaying the
# per-connection PRAGMA set is pure overhead on hot read/write paths. Each
# thread (event loop + FastAPI sync-endpoint threadpool) keeps at most one
# connection; WAL mode keeps cross-thread access safe.
_thread_local = threading.local()
_pooled_connections: set[sqlite3.Connection] = set()
_pool_lock = threading.Lock()


def _is_sqlite_locked(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return "database is locked" in message or "database table is locked" in message or "database schema is locked" in message


def _retry_sqlite_locked(operation: Callable[[], _T]) -> _T:
    for attempt in range(SQLITE_LOCK_RETRIES):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_locked(exc) or attempt >= SQLITE_LOCK_RETRIES - 1:
                raise
            time.sleep(min(SQLITE_LOCK_RETRY_DELAY_SECONDS * (2**attempt), 1.2))
    return operation()


class RetryingConnection(sqlite3.Connection):
    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return _retry_sqlite_locked(lambda: super(RetryingConnection, self).execute(*args, **kwargs))

    def executemany(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return _retry_sqlite_locked(lambda: super(RetryingConnection, self).executemany(*args, **kwargs))

    def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return _retry_sqlite_locked(lambda: super(RetryingConnection, self).executescript(*args, **kwargs))

    def commit(self) -> None:
        _retry_sqlite_locked(lambda: super(RetryingConnection, self).commit())


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
    # check_same_thread=False only widens *closing* to any thread (pool shutdown / test
    # teardown); each thread still only executes on its own pooled connection.
    conn = _retry_sqlite_locked(lambda: sqlite3.connect(settings.database_path, timeout=SQLITE_CONNECT_TIMEOUT_SECONDS, factory=RetryingConnection, check_same_thread=False))
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    path_key = str(settings.database_path)
    if path_key not in _wal_initialized_paths:
        with _db_lock:
            if path_key not in _wal_initialized_paths:
                conn.execute("PRAGMA journal_mode = WAL")
                _wal_initialized_paths.add(path_key)
    if path_key not in _analyze_initialized_paths:
        with _db_lock:
            if path_key not in _analyze_initialized_paths:
                try:
                    conn.execute("PRAGMA optimize")
                except Exception:
                    pass
                _analyze_initialized_paths.add(path_key)
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -65536")
        conn.execute("PRAGMA mmap_size = 268435456")
    except Exception:
        pass
    conn._database_path = str(settings.database_path)
    return conn


def _pooled_connection() -> sqlite3.Connection:
    conn = getattr(_thread_local, "connection", None)
    if conn is not None:
        if getattr(conn, "_database_path", None) != str(settings.database_path):
            # Tests swap the database path per class: rebuild for the new file.
            with _pool_lock:
                _pooled_connections.discard(conn)
            try:
                conn.close()
            except Exception:
                pass
            conn = None
        else:
            try:
                conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                # Someone closed the connection out-of-band; replace it.
                with _pool_lock:
                    _pooled_connections.discard(conn)
                conn = None
    if conn is None:
        conn = get_connection()
        with _pool_lock:
            _pooled_connections.add(conn)
        _thread_local.connection = conn
    return conn


def close_connection_pool() -> None:
    """Close every pooled connection (app shutdown / test isolation)."""
    with _pool_lock:
        conns = list(_pooled_connections)
        _pooled_connections.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:
            pass
    _thread_local.connection = None


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _pooled_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
