from abc import ABC, abstractmethod
from datetime import datetime

from src.modules.data_sync.domain.models.sync_job import SyncRunOutcome, SyncSource


class ISyncRunner(ABC):
    """Runs one business-data sync outside the web process and waits for it."""

    @abstractmethod
    async def run(
        self, source: SyncSource, *, allow_shrink: bool, timeout_seconds: int
    ) -> SyncRunOutcome:
        """Never raises for a failed sync: failures come back as ``SyncRunOutcome.failure``."""

    @abstractmethod
    def unavailable_reason(self, source: SyncSource) -> str | None:
        """Why ``source`` cannot run with the current configuration, or None if it can."""

    @abstractmethod
    def snapshot_modified_at(self) -> datetime | None:
        """Oldest modification time (timezone-aware) of the Excel snapshots, None if any is missing."""
