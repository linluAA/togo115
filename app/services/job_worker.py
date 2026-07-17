from __future__ import annotations

"""Background job worker for scheduled subscription tasks.

Jobs are enqueued by schedule_* helpers. This worker claims queued rows and
executes heavy work on a dedicated event loop in a worker thread so the API
loop stays responsive.
"""

import asyncio
from typing import Any

from app.db import add_log
from app.services.jobs import (
    claim_next_job,
    mark_job_done,
    mark_job_failed,
    requeue_stale_running_jobs,
    touch_job_heartbeat,
)
from app.services.search_metrics import record_job_event


SUPPORTED_KINDS = (
    "subscription_search",
    "subscription_search_all",
    "emby_subscription_sync",
    "recheck_pending_115",
    "retry_failed_resources",
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
        add_log("info", "jobs", '后台任务 worker 已启动')

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        add_log("info", "jobs", '后台任务 worker 已停止')

    async def _run(self) -> None:
        requeue_stale_running_jobs()
        last_requeue = 0.0
        while not self._stopping.is_set():
            try:
                now = asyncio.get_running_loop().time()
                if now - last_requeue > 60:
                    requeued = requeue_stale_running_jobs()
                    if requeued:
                        record_job_event({"kind": "requeue", "status": "requeued", "count": requeued})
                    last_requeue = now
                job = claim_next_job(list(SUPPORTED_KINDS))
                if not job:
                    await asyncio.sleep(self.poll_seconds)
                    continue
                await self._execute(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                add_log(
                    "error",
                    "jobs",
                    '后台任务 worker 循环异常',
                    {"error": str(exc), "error_type": type(exc).__name__},
                )
                await asyncio.sleep(self.poll_seconds)

    async def _execute(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        kind = str(job.get("kind") or "")
        started = asyncio.get_running_loop().time()
        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id), name=f"job-heartbeat-{job_id}")
        try:
            result = await asyncio.to_thread(self._dispatch_blocking, kind, job)
            mark_job_done(job_id, result if isinstance(result, dict) else {"ok": True})
            record_job_event(
                {
                    "kind": kind,
                    "status": "done",
                    "duration_ms": int((asyncio.get_running_loop().time() - started) * 1000),
                }
            )
        except Exception as exc:
            mark_job_failed(job_id, str(exc))
            record_job_event(
                {
                    "kind": kind,
                    "status": "failed",
                    "duration_ms": int((asyncio.get_running_loop().time() - started) * 1000),
                }
            )
            add_log(
                "error",
                "jobs",
                "????????",
                {"id": job_id, "kind": kind, "error": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self, job_id: int, interval: float = 15.0) -> None:
        while True:
            touch_job_heartbeat(job_id)
            await asyncio.sleep(interval)

    def _dispatch_blocking(self, kind: str, job: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._dispatch(kind, job))

    async def _dispatch(self, kind: str, job: dict[str, Any]) -> dict[str, Any]:
        if kind == "subscription_search":
            from app.services.subscription.search.tasks import (
                _default_search,
                _search_and_attach_resources_guarded,
            )

            subscription_id = int(job.get("target_id") or (job.get("payload") or {}).get("id") or 0)
            if subscription_id <= 0:
                raise RuntimeError("subscription_search missing target_id")
            created = await _search_and_attach_resources_guarded(
                subscription_id,
                search_func=_default_search,
            )
            return {"id": subscription_id, "created": len(created or [])}
        if kind == "subscription_search_all":
            from app.services.subscription.search.tasks import _default_search_all
            from app.services.subscription import runtime as runtime

            delay = float(getattr(runtime, "SEARCH_ALL_START_DELAY_SECONDS", 0) or 0)
            if delay > 0:
                await asyncio.sleep(delay)
            result = await _default_search_all()
            return result if isinstance(result, dict) else {"ok": True}
        if kind == "emby_subscription_sync":
            from app.services.subscription.search.tasks import _default_emby_sync
            from app.services.subscription import runtime as runtime

            delay = float(getattr(runtime, "EMBY_SYNC_START_DELAY_SECONDS", 0) or 0)
            if delay > 0:
                await asyncio.sleep(delay)
            result = await _default_emby_sync()
            return result if isinstance(result, dict) else {"ok": True}
        if kind == "recheck_pending_115":
            from app.services.subscription import recheck_pending_115_resources

            result = await recheck_pending_115_resources()
            return result if isinstance(result, dict) else {"ok": True, "result": result}
        if kind == "retry_failed_resources":
            from app.services.subscription import retry_failed_resources

            payload = job.get("payload") or {}
            limit = int(payload.get("limit") or 12)
            result = await retry_failed_resources(limit)
            return result if isinstance(result, dict) else {"ok": True, "result": result}
        raise RuntimeError(f"unsupported job kind: {kind}")


job_worker = JobWorker()
