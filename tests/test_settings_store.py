from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.db import db, init_db, json_dumps, json_loads, utc_now
from app.services.settings_store import export_backup, import_backup, list_settings, save_setting


class SettingsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-settings-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def test_save_and_list_settings_round_trip_json_value(self) -> None:
        result = save_setting("tmdb", {"api_key": "demo", "enabled": True})

        listed = list_settings()

        self.assertEqual(result, {"ok": True})
        self.assertEqual(listed["tmdb"]["value"], {"api_key": "demo", "enabled": True})
        self.assertTrue(listed["tmdb"]["updated_at"])

    def test_export_backup_serializes_subscription_json_fields(self) -> None:
        now = utc_now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES ('proxy', ?, ?)
                """,
                (json_dumps({"url": "http://127.0.0.1:7890"}), now),
            )
            conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, tmdb_id, keywords, quality_rules, tmdb_seasons,
                     emby_episode_keys, delivery_mode, target_path, created_at, updated_at)
                VALUES (?, 'tv', 123, ?, ?, ?, ?, '115', '/tv/Drama', ?, ?)
                """,
                (
                    "Drama",
                    json_dumps(["1080p"]),
                    json_dumps({"resolution": "1080p"}),
                    json_dumps([{"season_number": 1, "episode_count": 12}]),
                    json_dumps(["1x1", "1x2"]),
                    now,
                    now,
                ),
            )

        backup = export_backup()

        self.assertEqual(backup["version"], 1)
        self.assertEqual(backup["settings"]["proxy"], {"url": "http://127.0.0.1:7890"})
        self.assertEqual(backup["subscriptions"][0]["keywords"], ["1080p"])
        self.assertEqual(backup["subscriptions"][0]["quality_rules"], {"resolution": "1080p"})
        self.assertEqual(backup["subscriptions"][0]["tmdb_seasons"], [{"season_number": 1, "episode_count": 12}])
        self.assertEqual(backup["subscriptions"][0]["emby_episode_keys"], ["1x1", "1x2"])

    def test_import_backup_upserts_settings_and_subscriptions(self) -> None:
        payload = {
            "settings": {"delivery": {"mode": "115"}, "proxy": "ignored-non-dict"},
            "subscriptions": [
                {
                    "title": "Drama",
                    "media_type": "tv",
                    "tmdb_id": "456",
                    "poster_url": "poster.jpg",
                    "keywords": ["Drama", "1080p"],
                    "quality_rules": {"resolution": "1080p"},
                    "tmdb_seasons": [{"season_number": 1}],
                    "emby_episode_keys": ["1x1"],
                    "in_library": True,
                    "status": "active",
                    "target_path": "/tv/Drama",
                },
                {"title": "   "},
            ],
        }

        result = import_backup(payload)
        payload["subscriptions"][0]["poster_url"] = "new-poster.jpg"
        second = import_backup(payload)

        self.assertEqual(result, {"ok": True, "settings": 2, "subscriptions": 1})
        self.assertEqual(second, {"ok": True, "settings": 2, "subscriptions": 1})
        with db() as conn:
            settings_rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
            subscriptions = conn.execute("SELECT * FROM subscriptions").fetchall()
        setting_values = {row["key"]: json_loads(row["value"], {}) for row in settings_rows}
        self.assertEqual(setting_values["delivery"], {"mode": "115"})
        self.assertEqual(setting_values["proxy"], {})
        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions[0]["tmdb_id"], 456)
        self.assertEqual(subscriptions[0]["poster_url"], "new-poster.jpg")
        self.assertEqual(json_loads(subscriptions[0]["keywords"], []), ["Drama", "1080p"])
        self.assertEqual(json_loads(subscriptions[0]["emby_episode_keys"], []), ["1x1"])
        self.assertEqual(subscriptions[0]["in_library"], 1)

    def test_import_backup_rejects_invalid_shape(self) -> None:
        result = import_backup({"settings": [], "subscriptions": {}})

        self.assertEqual(result, {"ok": False, "error": "备份格式错误"})
