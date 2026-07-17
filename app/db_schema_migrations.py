from __future__ import annotations

import sqlite3


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = table_columns(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def migrate_schema(conn: sqlite3.Connection) -> None:
    ensure_columns(conn, "subscriptions", _SUBSCRIPTION_COLUMNS)
    ensure_columns(conn, "resources", _RESOURCE_COLUMNS)
    _ensure_telegram_message_index(conn)
    _ensure_telegram_message_index_columns(conn)
    _ensure_telegram_message_index_fts(conn)
    _ensure_telegram_dialog_entities(conn)
    _merge_duplicate_tmdb_subscriptions(conn)
    _delete_duplicate_resources(conn)
    _ensure_background_jobs(conn)
    _ensure_indexes(conn)


_SUBSCRIPTION_COLUMNS = {
    "title": "TEXT NOT NULL DEFAULT ''",
    "media_type": "TEXT NOT NULL DEFAULT 'tv'",
    "tmdb_id": "INTEGER",
    "poster_url": "TEXT",
    "overview": "TEXT",
    "release_year": "INTEGER",
    "keywords": "TEXT NOT NULL DEFAULT '[]'",
    "quality_rules": "TEXT NOT NULL DEFAULT '{}'",
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
}

_RESOURCE_COLUMNS = {
    "retry_count": "INTEGER NOT NULL DEFAULT 0",
    "last_error": "TEXT",
    "updated_at": "TEXT",
}


def _merge_duplicate_tmdb_subscriptions(conn: sqlite3.Connection) -> None:
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
              AND s1.status != 'completed'
              AND s2.status != 'completed'
        )
        WHERE subscription_id IN (
            SELECT s1.id
            FROM subscriptions s1
            JOIN subscriptions s2
              ON s1.media_type = s2.media_type
             AND s1.tmdb_id = s2.tmdb_id
             AND s2.id < s1.id
            WHERE s1.tmdb_id IS NOT NULL
              AND s1.status != 'completed'
              AND s2.status != 'completed'
        )
        """
    )
    conn.execute(
        """
        DELETE FROM subscriptions
        WHERE tmdb_id IS NOT NULL
          AND status != 'completed'
          AND id NOT IN (
              SELECT MIN(id)
              FROM subscriptions
              WHERE tmdb_id IS NOT NULL
                AND status != 'completed'
              GROUP BY media_type, tmdb_id
          )
        """
    )


def _delete_duplicate_resources(conn: sqlite3.Connection) -> None:
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




def _ensure_telegram_dialog_entities(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_dialog_entities (
            source TEXT PRIMARY KEY,
            peer_id TEXT NOT NULL,
            entity_id TEXT,
            access_hash TEXT,
            username TEXT,
            title TEXT,
            entity_type TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

def _ensure_telegram_message_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_message_index (
            source TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            search_blob TEXT NOT NULL DEFAULT '',
            has_115 INTEGER NOT NULL DEFAULT 0,
            has_link_hint INTEGER NOT NULL DEFAULT 0,
            message_date TEXT,
            indexed_at TEXT NOT NULL,
            PRIMARY KEY (source, message_id)
        )
        """
    )




def _ensure_telegram_message_index_columns(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(telegram_message_index)").fetchall()}
    if "search_blob" not in columns:
        conn.execute("ALTER TABLE telegram_message_index ADD COLUMN search_blob TEXT NOT NULL DEFAULT ''")



def _ensure_telegram_message_index_fts(conn: sqlite3.Connection) -> None:
    """Create FTS5 shadow index for search_blob when SQLite supports it."""
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS telegram_message_index_fts USING fts5(
                source UNINDEXED,
                message_id UNINDEXED,
                search_blob,
                content='telegram_message_index',
                content_rowid='rowid'
            )
            """
        )
    except sqlite3.OperationalError:
        # FTS5 unavailable in this SQLite build; LIKE path remains active.
        return

    # Keep triggers for content sync.
    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS telegram_message_index_ai AFTER INSERT ON telegram_message_index BEGIN
          INSERT INTO telegram_message_index_fts(rowid, source, message_id, search_blob)
          VALUES (new.rowid, new.source, new.message_id, new.search_blob);
        END;
        CREATE TRIGGER IF NOT EXISTS telegram_message_index_ad AFTER DELETE ON telegram_message_index BEGIN
          INSERT INTO telegram_message_index_fts(telegram_message_index_fts, rowid, source, message_id, search_blob)
          VALUES ('delete', old.rowid, old.source, old.message_id, old.search_blob);
        END;
        CREATE TRIGGER IF NOT EXISTS telegram_message_index_au AFTER UPDATE ON telegram_message_index BEGIN
          INSERT INTO telegram_message_index_fts(telegram_message_index_fts, rowid, source, message_id, search_blob)
          VALUES ('delete', old.rowid, old.source, old.message_id, old.search_blob);
          INSERT INTO telegram_message_index_fts(rowid, source, message_id, search_blob)
          VALUES (new.rowid, new.source, new.message_id, new.search_blob);
        END;
        """
    )

    # Bootstrap existing rows once if FTS is empty but base table is not.
    try:
        fts_count = conn.execute("SELECT COUNT(*) AS c FROM telegram_message_index_fts").fetchone()[0]
        base_count = conn.execute("SELECT COUNT(*) AS c FROM telegram_message_index").fetchone()[0]
        if int(base_count or 0) > 0 and int(fts_count or 0) == 0:
            conn.execute(
                """
                INSERT INTO telegram_message_index_fts(rowid, source, message_id, search_blob)
                SELECT rowid, source, message_id, search_blob FROM telegram_message_index
                """
            )
    except Exception:
        pass

def _ensure_background_jobs(conn: sqlite3.Connection) -> None:
    ensure_columns(
        conn,
        "background_jobs",
        {
            "heartbeat_at": "TEXT",
            "worker_id": "TEXT",
        },
    )

def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP INDEX IF EXISTS idx_subscriptions_tmdb_unique;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_tmdb_unique
            ON subscriptions(media_type, tmdb_id)
            WHERE tmdb_id IS NOT NULL AND status != 'completed';
        CREATE INDEX IF NOT EXISTS idx_subscriptions_status
            ON subscriptions(status);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_media_title
            ON subscriptions(media_type, title);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_subscription_url
            ON resources(subscription_id, url);
        CREATE INDEX IF NOT EXISTS idx_resources_status
            ON resources(status);
        CREATE INDEX IF NOT EXISTS idx_resources_status_retry
            ON resources(status, retry_count);
        CREATE INDEX IF NOT EXISTS idx_source_stats_updated_at
            ON source_stats(updated_at);
        CREATE INDEX IF NOT EXISTS idx_logs_created_at
            ON logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_telegram_scan_cursors_updated_at
            ON telegram_scan_cursors(updated_at);
        CREATE INDEX IF NOT EXISTS idx_telegram_dialog_entities_peer_id
            ON telegram_dialog_entities(peer_id);
        CREATE INDEX IF NOT EXISTS idx_telegram_dialog_entities_updated_at
            ON telegram_dialog_entities(updated_at);
        CREATE INDEX IF NOT EXISTS idx_telegram_message_index_source_id
            ON telegram_message_index(source, message_id DESC);
        CREATE INDEX IF NOT EXISTS idx_telegram_message_index_source_has115
            ON telegram_message_index(source, has_115, message_id DESC);
        -- search_blob is filtered with FTS5 (preferred) or LIKE; composite source/has_115 prunes rows.
        CREATE INDEX IF NOT EXISTS idx_resources_subscription_status
            ON resources(subscription_id, status);
        CREATE INDEX IF NOT EXISTS idx_telegram_message_index_indexed_at
            ON telegram_message_index(indexed_at);
        CREATE INDEX IF NOT EXISTS idx_background_jobs_kind_status
            ON background_jobs(kind, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_background_jobs_target
            ON background_jobs(kind, target_id, updated_at);
        """
    )
