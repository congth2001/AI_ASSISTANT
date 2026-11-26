"""HTTP contracts of the admin data-sync screen."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.modules.data_sync.domain.models.sync_job import SyncJobStatus, SyncSource


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StartSyncJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SyncSource = SyncSource.MDB
    # Lets the sync soft-delete records when the snapshot is empty or much smaller.
    allow_shrink: bool = False
    # Confirms loading Excel snapshots older than the last extraction from the sales software.
    allow_stale_snapshot: bool = False


class SyncJobResponse(_FromAttributes):
    id: str
    source: SyncSource
    status: SyncJobStatus
    allow_shrink: bool
    triggered_by_id: str | None
    triggered_by_name: str | None
    created_at: datetime
    finished_at: datetime | None
    # Sync summary (counts; money as strings) on success.
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


class SyncJobPageResponse(BaseModel):
    items: list[SyncJobResponse]
    has_more: bool


class SyncSourceResponse(_FromAttributes):
    source: SyncSource
    available: bool
    reason: str | None


class SnapshotStatusResponse(_FromAttributes):
    files_modified_at: datetime | None
    latest_extraction_at: datetime | None
    is_stale: bool


class DataSyncStatusResponse(_FromAttributes):
    sources: list[SyncSourceResponse]
    running_job: SyncJobResponse | None
    last_job: SyncJobResponse | None
    timeout_seconds: int
    snapshot: SnapshotStatusResponse | None
