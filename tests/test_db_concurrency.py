import concurrent.futures
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.config import settings
from app import db as db_module
from app.db import add_log, db, init_db
from app.services.jobs import create_job, latest_job, list_jobs, mark_job_done, mark_job_failed, mark_job_running


class DatabaseConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def test_concurrent_log_writes_are_serialized(self) -> None:
        def write_log(index: int) -> None:
            add_log("info", "test", "concurrent log", {"index": index})

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(write_log, index) for index in range(180)]
            for future in futures:
                future.result()

        with db() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM logs WHERE scope = 'test'").fetchone()["count"]

        self.assertEqual(count, 180)


    def test_background_jobs_track_state_transitions(self) -> None:
        job_id = create_job("subscription_search", 12, {"title": "将夜"})
        mark_job_running(job_id)
        mark_job_done(job_id, {"created": 2})

        job = latest_job("subscription_search", 12)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["payload"], {"title": "将夜"})
        self.assertEqual(job["result"], {"created": 2})

    def test_background_jobs_record_failures(self) -> None:
        job_id = create_job("subscription_search_all")
        mark_job_failed(job_id, "timeout")

        jobs = list_jobs(status="failed")

        self.assertEqual(jobs[0]["id"], job_id)
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[0]["error"], "timeout")


    def test_log_payload_sanitizes_telegram_bot_token(self) -> None:
        token = "1234567890:" + "abcdefghijklmnopqrstuvwxyzABCDEFGH"
        url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=25"

        add_log("warning", "tg_bot", f"request failed {url}", {"error": url, "nested": {"token": token}})

        with db() as conn:
            row = conn.execute("SELECT message, payload FROM logs WHERE scope = 'tg_bot' ORDER BY id DESC LIMIT 1").fetchone()

        self.assertNotIn(token, row["message"])
        self.assertNotIn(token, row["payload"])
        self.assertIn("bot***", row["message"])
        self.assertIn("***", row["payload"])

    def test_locked_log_write_does_not_break_business_flow(self) -> None:
        old_db = db_module.db

        @contextmanager
        def locked_db():
            raise sqlite3.OperationalError("database is locked")
            yield

        db_module.db = locked_db
        try:
            db_module.add_log("info", "test", "lock should be ignored", {"ok": True})
        finally:
            db_module.db = old_db


if __name__ == "__main__":
    unittest.main()
