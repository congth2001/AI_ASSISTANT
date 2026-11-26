from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping

from src.modules.data_sync.domain.models.sync_job import (
    NewSyncJob,
    SyncJob,
    SyncJobPage,
    SyncJobStatus,
)

MAX_SYNC_JOB_PAGE_SIZE = 50


class ISyncJobRepository(ABC):
    @abstractmethod
    async def create_running(self, job: NewSyncJob) -> SyncJob:
        """Insert a running job.

        Raises ``SyncJobAlreadyRunningError`` when another job is still running; the
        database enforces at most one running job, so concurrent requests cannot both win.
        """

    @abstractmethod
    async def touch(self, job_id: str, at: datetime) -> None:
        """Record that the process watching ``job_id`` is still alive."""

    @abstractmethod
    async def finish(
        self,
        job_id: str,
        *,
        status: SyncJobStatus,
        finished_at: datetime,
        result: Mapping[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        """Close a running job; a job that is no longer running is left unchanged."""

    @abstractmethod
    async def fail_stale(
        self, heartbeat_before: datetime, *, finished_at: datetime, error_code: str, message: str
    ) -> int:
        """Fail running jobs whose watcher stopped sending heartbeats; returns how many."""

    @abstractmethod
    async def get(self, job_id: str) -> SyncJob | None:
        ...

    @abstractmethod
    async def get_running(self) -> SyncJob | None:
        ...

    @abstractmethod
    async def list_recent(self, limit: int, offset: int) -> SyncJobPage:
        """Newest first."""
