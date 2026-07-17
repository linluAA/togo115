from __future__ import annotations

"""Background job worker for scheduled subscription tasks.

Jobs are still enqueued by schedule_* helpers. This worker claims queued rows and
executes them, so /api/jobs reflects a real queue rather than fire-and-forget only.
"""


import asyncio
from typing import Any

from app.db import add_log
from app.services.jobs import claim_next_job, mark_job_done, mark_job_failed, requeue_stale_running_jobs


SUPPORTED_KINDS = (
    "subscription_search",
    "subscription_search_all",
    "emby_subscription_sync",
)


class JobWorker:
    def __init__(self, poll_seconds: float = 1.0) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.poll_seconds = poll_seconds

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="togo115-job-worker")
        add_log("info", "jobs", "后台任务 worker 已启动")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        add_log("info", "jobs", "后台任务 worker 已停止")

    async def _run(self) -> None:
        requeue_stale_running_jobs()
        while not self._stopping.is_set():
            try:
                job = claim_next_job(list(SUPPORTED_KINDS))
                if not job:
                    await asyncio.sleep(self.poll_seconds)
                    continue
                await self._execute(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                add_log("error", "jobs", "后台任务 worker 循环异常", {"error": str(exc), "error_type": type(exc).__name__})
                await asyncio.sleep(self.poll_seconds)

    async def _execute(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        kind = str(job.get("kind") or "")
        try:
            result = await self._dispatch(kind, job)
            mark_job_done(job_id, result if isinstance(result, dict) else {"ok": True})
        except Exception as exc:
            mark_job_failed(job_id, str(exc))
            add_log(
                "error",
                "jobs",
                "后台任务执行失败",
                {"id": job_id, "kind": kind, "error": str(exc), "error_type": type(exc).__name__},
            )

    async def _dispatch(self, kind: str, job: dict[str, Any]) -> dict[str, Any]:
        if kind == "subscription_search":
            from app.services.subscription.search.tasks import _search_and_attach_resources_guarded

            subscription_id = int(job.get("target_id") or (job.get("payload") or {}).get("id") or 0)
            if subscription_id <= 0:
                raise RuntimeError("subscription_search missing target_id")
            created = await _search_and_attach_resources_guarded(subscription_id)
            return {"id": subscription_id, "created": len(created or [])}
        if kind == "subscription_search_all":
            from app.services.subscription.search.all import search_all_active_subscriptions

            result = await search_all_active_subscriptions()
            return result if isinstance(result, dict) else {"ok": True}
        if kind == "emby_subscription_sync":
            from app.services.subscription.crud.service import list_subscriptions
            from app.services.subscription.library.service import sync_subscription_list_with_emby

            result = await sync_subscription_list_with_emby(list_subscriptions(include_completed=True), force=True)
            return result if isinstance(result, dict) else {"ok": True}
        raise RuntimeError(f"unsupported job kind: {kind}")


job_worker = JobWorker()

