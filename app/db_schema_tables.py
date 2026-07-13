from __future__ import annotations

import sqlite3


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


SCHEMA_SQL = """
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
            quality_rules TEXT NOT NULL DEFAULT '{}',
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
            retry_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS source_stats (
            source_key TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            match_count INTEGER NOT NULL DEFAULT 0,
            last_items INTEGER NOT NULL DEFAULT 0,
            last_latency_ms INTEGER,
            last_success_at TEXT,
            last_error_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
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

        CREATE TABLE IF NOT EXISTS telegram_scan_cursors (
            source TEXT PRIMARY KEY,
            last_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS telegram_message_index (
            source TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            has_115 INTEGER NOT NULL DEFAULT 0,
            has_link_hint INTEGER NOT NULL DEFAULT 0,
            message_date TEXT,
            indexed_at TEXT NOT NULL,
            PRIMARY KEY (source, message_id)
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            target_id INTEGER,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
            payload TEXT NOT NULL DEFAULT '{}',
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL
        );

"""
