"""Business-data sync jobs started from the admin screen."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class SyncSource(str, Enum):
    """What a sync job reads.

    ``mdb``: full ETL (sales software database -> Excel snapshots -> PostgreSQL),
    same as ``run_business_etl.py``. ``snapshot``: reload the Excel snapshots already
    in ``data/documents/``, same as ``sync_business_data.py``.
    """

    MDB = "mdb"
    SNAPSHOT = "snapshot"


class SyncJobStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# ``etl_sync_runs.entrypoint`` written by the admin screen, per source.
ENTRYPOINT_BY_SOURCE = {
    SyncSource.MDB: "admin_etl_job",
    SyncSource.SNAPSHOT: "admin_sync_business_data",
}
# Runs that extract from the sales software and promote fresh Excel snapshots
# (cron/CLI ``run_business_etl.py`` and the admin screen).
EXTRACTION_ENTRYPOINTS = frozenset({"etl_job", ENTRYPOINT_BY_SOURCE[SyncSource.MDB]})

# Error codes reported by the sync worker process (see etl_business/sync_worker.py).
WORKER_ALREADY_RUNNING = "already_running"
WORKER_TIMEOUT = "timeout"
WORKER_CRASHED = "worker_crashed"
WORKER_INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class SyncJob:
    id: str
    source: SyncSource
    status: SyncJobStatus
    allow_shrink: bool
    created_at: datetime
    heartbeat_at: datetime
    triggered_by_id: str | None = None
    triggered_by_name: str | None = None
    finished_at: datetime | None = None
    result: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_running(self) -> bool:
        return self.status is SyncJobStatus.RUNNING


@dataclass(frozen=True)
class NewSyncJob:
    source: SyncSource
    allow_shrink: bool
    triggered_by_id: str | None
    started_at: datetime


@dataclass(frozen=True)
class SyncJobPage:
    items: list[SyncJob]
    has_more: bool


@dataclass(frozen=True)
class SyncRunOutcome:
    """What the worker process reported. ``result`` is the sync summary on success."""

    succeeded: bool
    result: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def success(cls, result: Mapping[str, Any]) -> "SyncRunOutcome":
        return cls(succeeded=True, result=result)

    @classmethod
    def failure(cls, code: str, message: str) -> "SyncRunOutcome":
        return cls(succeeded=False, error_code=code, error_message=message)


@dataclass(frozen=True)
class SyncSourceAvailability:
    source: SyncSource
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class SnapshotStatus:
    """Age of the Excel snapshots that the ``snapshot`` source would load.

    ``files_modified_at`` is the oldest modification time among the snapshot files.
    The snapshots are stale when an extraction run finished after that: the database
    then holds data the files do not, and loading them would roll it back.
    """

    files_modified_at: datetime | None
    latest_extraction_at: datetime | None

    @property
    def is_stale(self) -> bool:
        return (
            self.files_modified_at is not None
            and self.latest_extraction_at is not None
            and self.files_modified_at < self.latest_extraction_at
        )


@dataclass(frozen=True)
class DataSyncStatus:
    sources: list[SyncSourceAvailability] = field(default_factory=list)
    running_job: SyncJob | None = None
    last_job: SyncJob | None = None
    timeout_seconds: int = 0
    snapshot: SnapshotStatus | None = None
