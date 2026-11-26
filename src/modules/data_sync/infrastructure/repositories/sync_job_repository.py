from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.common.domain.time import as_vietnam_time
from src.modules.auth.infrastructure.models import UserModel
from src.modules.data_sync.domain.errors import SyncJobAlreadyRunningError
from src.modules.data_sync.domain.models.sync_job import (
    NewSyncJob,
    SyncJob,
    SyncJobPage,
    SyncJobStatus,
    SyncSource,
)
from src.modules.data_sync.domain.repositories.i_sync_job_repository import (
    MAX_SYNC_JOB_PAGE_SIZE,
    ISyncJobRepository,
)
from src.modules.data_sync.infrastructure.models import SINGLE_RUNNING_INDEX, DataSyncJobModel

_RUNNING = SyncJobStatus.RUNNING.value


def _to_domain(model: DataSyncJobModel, user: UserModel | None) -> SyncJob:
    return SyncJob(
        id=model.id,
        source=SyncSource(model.source),
        status=SyncJobStatus(model.status),
        allow_shrink=bool(model.allow_shrink),
        created_at=as_vietnam_time(model.created_at),
        heartbeat_at=as_vietnam_time(model.heartbeat_at),
        triggered_by_id=model.triggered_by_id,
        triggered_by_name=user.display_name if user is not None else None,
        finished_at=as_vietnam_time(model.finished_at),
        result=model.result,
        error_code=model.error_code,
        error_message=model.error_message,
    )


class SyncJobRepository(ISyncJobRepository):
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _select(self):
        return select(DataSyncJobModel, UserModel).outerjoin(
            UserModel, UserModel.id == DataSyncJobModel.triggered_by_id
        )

    async def create_running(self, job: NewSyncJob) -> SyncJob:
        model = DataSyncJobModel(
            id=str(uuid4()),
            source=job.source.value,
            status=_RUNNING,
            allow_shrink=job.allow_shrink,
            triggered_by_id=job.triggered_by_id,
            created_at=job.started_at,
            heartbeat_at=job.started_at,
        )
        async with self._session_factory() as session:
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if SINGLE_RUNNING_INDEX in str(exc.orig):
                    raise SyncJobAlreadyRunningError() from exc
                raise
        created = await self.get(model.id)
        assert created is not None
        return created

    async def touch(self, job_id: str, at: datetime) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(DataSyncJobModel)
                .where(DataSyncJobModel.id == job_id, DataSyncJobModel.status == _RUNNING)
                .values(heartbeat_at=at)
            )
            await session.commit()

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
        async with self._session_factory() as session:
            await session.execute(
                update(DataSyncJobModel)
                .where(DataSyncJobModel.id == job_id, DataSyncJobModel.status == _RUNNING)
                .values(
                    status=status.value,
                    finished_at=finished_at,
                    heartbeat_at=finished_at,
                    result=dict(result) if result is not None else None,
                    error_code=error_code,
                    error_message=error_message,
                )
            )
            await session.commit()

    async def fail_stale(
        self, heartbeat_before: datetime, *, finished_at: datetime, error_code: str, message: str
    ) -> int:
        async with self._session_factory() as session:
            outcome = await session.execute(
                update(DataSyncJobModel)
                .where(
                    DataSyncJobModel.status == _RUNNING,
                    DataSyncJobModel.heartbeat_at < heartbeat_before,
                )
                .values(
                    status=SyncJobStatus.FAILED.value,
                    finished_at=finished_at,
                    error_code=error_code,
                    error_message=message,
                )
            )
            await session.commit()
            return outcome.rowcount or 0

    async def get(self, job_id: str) -> SyncJob | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(self._select().where(DataSyncJobModel.id == job_id))
            ).first()
            return _to_domain(*row) if row else None

    async def get_running(self) -> SyncJob | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(self._select().where(DataSyncJobModel.status == _RUNNING))
            ).first()
            return _to_domain(*row) if row else None

    async def list_recent(self, limit: int, offset: int) -> SyncJobPage:
        limit = max(1, min(int(limit), MAX_SYNC_JOB_PAGE_SIZE))
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    self._select()
                    .order_by(DataSyncJobModel.created_at.desc(), DataSyncJobModel.id.desc())
                    # One extra row tells whether another page exists without a COUNT.
                    .limit(limit + 1)
                    .offset(max(0, int(offset)))
                )
            ).all()
        return SyncJobPage(
            items=[_to_domain(job, user) for job, user in rows[:limit]],
            has_more=len(rows) > limit,
        )
