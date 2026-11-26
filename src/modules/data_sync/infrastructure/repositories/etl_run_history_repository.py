from datetime import datetime

from sqlalchemy import func, select

from src.common.domain.time import as_vietnam_time
from src.modules.data_sync.domain.repositories.i_etl_run_history import IEtlRunHistory
from src.modules.sales.infrastructure.models import EtlSyncRun


class EtlRunHistoryRepository(IEtlRunHistory):
    """Read-only view of the sales sync audit rows."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def latest_finished_at(self, entrypoints: frozenset[str]) -> datetime | None:
        async with self._session_factory() as session:
            value = (
                await session.execute(
                    select(func.max(EtlSyncRun.finished_at)).where(
                        EtlSyncRun.entrypoint.in_(sorted(entrypoints))
                    )
                )
            ).scalar_one_or_none()
        return as_vietnam_time(value)
