from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from app.db import db
from app.services.job_worker import JobWorker
from app.services.jobs import claim_next_job, create_job, list_jobs, requeue_stale_running_jobs
from app.services.subscription.search import tasks as subscription_tasks


class JobWorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        with db() as conn:
            conn.execute("DELETE FROM background_jobs")

    def test_claim_next_job_is_exclusive(self) -> None:
        job_id = create_job("subscription_search_all")
        first = claim_next_job(["subscription_search_all"])
        second = claim_next_job(["subscription_search_all"])
        self.assertIsNotNone(first)
        self.assertEqual(first["id"], job_id)
        self.assertEqual(first["status"], "running")
        self.assertIsNone(second)

    def test_requeue_stale_running_jobs(self) -> None:
        job_id = create_job("subscription_search_all")
        claimed = claim_next_job(["subscription_search_all"])
        self.assertIsNotNone(claimed)
        with db() as conn:
            conn.execute(
                "UPDATE background_jobs SET started_at = ?, updated_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", job_id),
            )
        count = requeue_stale_running_jobs(max_age_seconds=60)
        self.assertEqual(count, 1)
        jobs = list_jobs(status="queued")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], job_id)

    async def test_worker_executes_search_all_off_loop(self) -> None:
        done = {"value": False}

        async def fake_search_all():
            time.sleep(0.05)
            done["value"] = True
            return {"ok": True, "searched": 1}

        worker = JobWorker(poll_seconds=0.05)
        with patch.object(subscription_tasks, "_default_search_all", fake_search_all), patch(
            "app.services.subscription.runtime.SEARCH_ALL_START_DELAY_SECONDS",
            0,
        ):
            result = subscription_tasks.schedule_search_all_active_subscriptions()
            worker.start()
            try:
                for _ in range(40):
                    jobs = [j for j in list_jobs() if j.get("id") == result.get("job_id")]
                    if jobs and jobs[0].get("status") == "done":
                        break
                    await asyncio.sleep(0.05)
                else:
                    self.fail("job not done")
            finally:
                await worker.stop()
        self.assertTrue(done["value"])


    def test_schedule_recheck_enqueues(self) -> None:
        from app.services.subscription.search import tasks as subscription_tasks

        first = subscription_tasks.schedule_recheck_pending_115()
        second = subscription_tasks.schedule_recheck_pending_115()
        self.assertEqual(first.get("job_id"), second.get("job_id"))
        jobs = [j for j in list_jobs() if j.get("kind") == "recheck_pending_115"]
        self.assertEqual(len(jobs), 1)

    def test_schedule_retry_failed_enqueues(self) -> None:
        from app.services.subscription.search import tasks as subscription_tasks

        first = subscription_tasks.schedule_retry_failed_resources(8)
        second = subscription_tasks.schedule_retry_failed_resources(8)
        self.assertEqual(first.get("job_id"), second.get("job_id"))
        jobs = [j for j in list_jobs() if j.get("kind") == "retry_failed_resources"]
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
