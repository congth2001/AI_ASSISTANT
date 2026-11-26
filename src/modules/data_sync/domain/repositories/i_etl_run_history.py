from abc import ABC, abstractmethod
from datetime import datetime


class IEtlRunHistory(ABC):
    """Read side of ``etl_sync_runs`` (written by the sales sync, any entry point)."""

    @abstractmethod
    async def latest_finished_at(self, entrypoints: frozenset[str]) -> datetime | None:
        """When the newest successful run with one of ``entrypoints`` finished."""
