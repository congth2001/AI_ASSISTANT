"""Start business-data syncs from the admin screen and keep their history."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from src.common.domain.time import as_vietnam_time, now_vietnam
from src.modules.data_sync.domain.errors import (
    SyncJobNotFoundError,
    SyncSnapshotStaleError,
    SyncSourceUnavailableError,
)
from src.modules.data_sync.domain.models.sync_job import (
    EXTRACTION_ENTRYPOINTS,
    WORKER_CRASHED,
    WORKER_INTERRUPTED,
    DataSyncStatus,
    NewSyncJob,
    SyncJob,
    SyncJobPage,
    SyncJobStatus,
    SnapshotStatus,
    SyncRunOutcome,
    SyncSource,
    SyncSourceAvailability,
)
from src.modules.data_sync.domain.ports.i_sync_runner import ISyncRunner
from src.modules.data_sync.domain.repositories.i_etl_run_history import IEtlRunHistory
from src.modules.data_sync.domain.repositories.i_sync_job_repository import (
    MAX_SYNC_JOB_PAGE_SIZE,
    ISyncJobRepository,
)

logger = logging.getLogger(__name__)

STALE_JOB_MESSAGE = (
    "Backend dừng hoặc khởi động lại trong lúc đồng bộ nên không ghi nhận được kết quả. "
    "Xem thời điểm nạp gần nhất để biết dữ liệu đã được cập nhật hay chưa."
)
SHUTDOWN_MESSAGE = "Backend dừng trong lúc đồng bộ; tiến trình đồng bộ đã bị huỷ và dữ liệu không thay đổi."
CRASH_MESSAGE = "Không chạy được tiến trình đồng bộ. Xem log backend để biết chi tiết."


def _display_time(value: datetime) -> str:
    return as_vietnam_time(value).strftime("%d/%m/%Y %H:%M")


class DataSyncUseCase:
    """One sync at a time, run by ``ISyncRunner`` in the background of this process.

    The process that started a job sends a heartbeat while it waits. A running job whose
    heartbeat stopped (backend restarted or crashed) is closed as failed the next time
    anyone reads the status or starts a job, so a lost job never blocks new syncs.
    """

    def __init__(
        self,
        repository: ISyncJobRepository,
        runner: ISyncRunner,
        run_history: IEtlRunHistory,
        timeout_seconds: int,
        heartbeat_seconds: float = 30,
        stale_after_seconds: float = 120,
        clock: Callable[[], datetime] = now_vietnam,
    ):
        self._repository = repository
        self._runner = runner
        self._run_history = run_history
        self._timeout_seconds = timeout_seconds
        self._heartbeat_seconds = heartbeat_seconds
        # A live job must miss at least two heartbeats before it counts as lost.
        self._stale_after = timedelta(seconds=max(stale_after_seconds, 2 * heartbeat_seconds))
        self._clock = clock
        self._tasks: set[asyncio.Task] = set()

    async def get_status(self) -> DataSyncStatus:
        await self._fail_stale_jobs()
        running = await self._repository.get_running()
        recent = await self._repository.list_recent(1, 0)
        return DataSyncStatus(
            sources=[
                SyncSourceAvailability(source, reason is None, reason)
                for source in SyncSource
                for reason in (self._runner.unavailable_reason(source),)
            ],
            running_job=running,
            last_job=recent.items[0] if recent.items else None,
            timeout_seconds=self._timeout_seconds,
            snapshot=await self._snapshot_status(),
        )

    async def list_jobs(self, limit: int, offset: int) -> SyncJobPage:
        await self._fail_stale_jobs()
        limit = max(1, min(int(limit), MAX_SYNC_JOB_PAGE_SIZE))
        return await self._repository.list_recent(limit, max(0, int(offset)))

    async def get_job(self, job_id: str) -> SyncJob:
        await self._fail_stale_jobs()
        job = await self._repository.get(job_id)
        if job is None:
            raise SyncJobNotFoundError()
        return job

    async def start(
        self,
        source: SyncSource,
        *,
        allow_shrink: bool,
        triggered_by_id: str | None,
        allow_stale_snapshot: bool = False,
    ) -> SyncJob:
        """``allow_stale_snapshot`` confirms loading snapshots older than the last extraction."""
        reason = self._runner.unavailable_reason(source)
        if reason is not None:
            raise SyncSourceUnavailableError(source=source.value, reason=reason)
        if source is SyncSource.SNAPSHOT and not allow_stale_snapshot:
            snapshot = await self._snapshot_status()
            if snapshot.is_stale:
                raise SyncSnapshotStaleError(
                    files_modified_at=_display_time(snapshot.files_modified_at),
                    latest_extraction_at=_display_time(snapshot.latest_extraction_at),
                )
        await self._fail_stale_jobs()
        job = await self._repository.create_running(
            NewSyncJob(
                source=source,
                allow_shrink=allow_shrink,
                triggered_by_id=triggered_by_id,
                started_at=self._clock(),
            )
        )
        logger.info(
            "Data sync job %s started by %s (source=%s, allow_shrink=%s, allow_stale_snapshot=%s)",
            job.id, triggered_by_id, source.value, allow_shrink, allow_stale_snapshot,
        )
        task = asyncio.create_task(self._watch(job), name=f"data-sync-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def wait_idle(self) -> None:
        """Wait for the jobs started by this process (tests, graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel running jobs: the runner stops its process, the job is closed as failed."""
        for task in list(self._tasks):
            task.cancel()
        await self.wait_idle()

    async def _watch(self, job: SyncJob) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        cancelled = False
        try:
            outcome = await self._runner.run(
                job.source, allow_shrink=job.allow_shrink, timeout_seconds=self._timeout_seconds
            )
        except asyncio.CancelledError:
            cancelled = True
            outcome = SyncRunOutcome.failure(WORKER_INTERRUPTED, SHUTDOWN_MESSAGE)
        except Exception:
            logger.exception("Data sync job %s could not run", job.id)
            outcome = SyncRunOutcome.failure(WORKER_CRASHED, CRASH_MESSAGE)
        finally:
            heartbeat.cancel()
        await self._finish(job, outcome)
        if cancelled:
            raise asyncio.CancelledError()

    async def _finish(self, job: SyncJob, outcome: SyncRunOutcome) -> None:
        status = SyncJobStatus.SUCCEEDED if outcome.succeeded else SyncJobStatus.FAILED
        try:
            await self._repository.finish(
                job.id,
                status=status,
                finished_at=self._clock(),
                result=outcome.result,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
            )
        except Exception:
            # The heartbeat has stopped, so the job is failed as stale later on.
            logger.exception("Could not record the end of data sync job %s", job.id)
            return
        if outcome.succeeded:
            logger.info("Data sync job %s succeeded", job.id)
        else:
            logger.warning(
                "Data sync job %s failed (%s): %s", job.id, outcome.error_code, outcome.error_message
            )

    async def _heartbeat(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                await self._repository.touch(job_id, self._clock())
            except Exception:
                logger.warning("Could not record heartbeat of data sync job %s", job_id, exc_info=True)

    async def _snapshot_status(self) -> SnapshotStatus:
        return SnapshotStatus(
            files_modified_at=self._runner.snapshot_modified_at(),
            latest_extraction_at=await self._run_history.latest_finished_at(EXTRACTION_ENTRYPOINTS),
        )

    async def _fail_stale_jobs(self) -> None:
        now = self._clock()
        count = await self._repository.fail_stale(
            now - self._stale_after,
            finished_at=now,
            error_code=WORKER_INTERRUPTED,
            message=STALE_JOB_MESSAGE,
        )
        if count:
            logger.warning("Closed %d data sync job(s) whose backend process stopped", count)
