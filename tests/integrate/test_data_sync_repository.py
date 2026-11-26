"""Opt-in PostgreSQL tests of SyncJobRepository, in a rolled-back transaction.

Tables are created in ``pg_temp`` from the ORM metadata inside one outer transaction
that is always rolled back; no public table is read or written.

Run with AI_SALES_TEST_DSN (or AI_ANALYTICS_TEST_DSN) for a dedicated database, or
AI_ANALYTICS_LOCAL_DB_TEST=1 for the configured local PostgreSQL.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.config_manager import get_database_settings
from src.common.domain.time import VIETNAM_TIMEZONE
from src.common.infrastructure.database.base import Base
from src.modules.auth.infrastructure.models import UserModel
from src.modules.data_sync.domain.errors import SyncJobAlreadyRunningError
from src.modules.data_sync.domain.models.sync_job import NewSyncJob, SyncJobStatus, SyncSource
from src.modules.data_sync.infrastructure.models import DataSyncJobModel
from src.modules.data_sync.infrastructure.repositories.sync_job_repository import (
    SyncJobRepository,
)

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=VIETNAM_TIMEZONE)


def _dsn() -> str:
    dsn = os.getenv("AI_SALES_TEST_DSN") or os.getenv("AI_ANALYTICS_TEST_DSN")
    if dsn:
        return dsn
    if os.getenv("AI_ANALYTICS_LOCAL_DB_TEST") == "1":
        return get_database_settings().sqlalchemy_url
    pytest.skip("Set AI_SALES_TEST_DSN, AI_ANALYTICS_TEST_DSN or AI_ANALYTICS_LOCAL_DB_TEST=1")


@pytest_asyncio.fixture
async def repository():
    engine = create_async_engine(_dsn(), echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            await connection.execute(text("SET LOCAL search_path TO pg_temp"))
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=[UserModel.__table__, DataSyncJobModel.__table__]
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, display_name, password_hash, role, is_active) "
                    "VALUES ('admin-1', 'a@example.com', 'Quản trị', 'x', 'admin', true)"
                )
            )

            @asynccontextmanager
            async def session_scope():
                session = AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
                )
                try:
                    yield session
                finally:
                    await session.close()

            yield SyncJobRepository(lambda: session_scope())
            await outer.rollback()
    finally:
        await engine.dispose()


def new_job(started_at=NOW, source=SyncSource.MDB):
    return NewSyncJob(source=source, allow_shrink=False, triggered_by_id="admin-1", started_at=started_at)


@pytest.mark.asyncio
async def test_single_running_job_lifecycle(repository):
    job = await repository.create_running(new_job())
    assert job.triggered_by_name == "Quản trị"
    assert (await repository.get_running()).id == job.id

    with pytest.raises(SyncJobAlreadyRunningError):
        await repository.create_running(new_job(source=SyncSource.SNAPSHOT))

    await repository.finish(
        job.id, status=SyncJobStatus.SUCCEEDED, finished_at=NOW + timedelta(minutes=2),
        result={"invoices": 4, "sync_run": {"retroactive_delta": "1.50"}},
        error_code=None, error_message=None,
    )
    finished = await repository.get(job.id)
    assert finished.status is SyncJobStatus.SUCCEEDED
    assert finished.result["sync_run"]["retroactive_delta"] == "1.50"
    assert await repository.get_running() is None

    # A finished job is never reopened or overwritten.
    await repository.finish(
        job.id, status=SyncJobStatus.FAILED, finished_at=NOW, result=None,
        error_code="late", error_message="late",
    )
    assert (await repository.get(job.id)).status is SyncJobStatus.SUCCEEDED

    second = await repository.create_running(new_job(started_at=NOW + timedelta(minutes=5)))
    page = await repository.list_recent(1, 0)
    assert [item.id for item in page.items] == [second.id] and page.has_more is True


@pytest.mark.asyncio
async def test_fail_stale_only_closes_jobs_without_recent_heartbeat(repository):
    job = await repository.create_running(new_job())
    await repository.touch(job.id, NOW + timedelta(minutes=3))

    assert await repository.fail_stale(
        NOW + timedelta(minutes=2), finished_at=NOW, error_code="interrupted", message="m"
    ) == 0
    assert await repository.fail_stale(
        NOW + timedelta(minutes=4), finished_at=NOW, error_code="interrupted", message="m"
    ) == 1
    stale = await repository.get(job.id)
    assert (stale.status, stale.error_code) == (SyncJobStatus.FAILED, "interrupted")


@pytest.mark.asyncio
async def test_latest_extraction_ignores_snapshot_reloads():
    from src.modules.data_sync.domain.models.sync_job import EXTRACTION_ENTRYPOINTS
    from src.modules.data_sync.infrastructure.repositories.etl_run_history_repository import (
        EtlRunHistoryRepository,
    )
    from src.modules.sales.infrastructure.models import EtlSyncRun

    engine = create_async_engine(_dsn(), echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            await connection.execute(text("SET LOCAL search_path TO pg_temp"))
            await connection.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[EtlSyncRun.__table__])
            )

            @asynccontextmanager
            async def session_scope():
                session = AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
                )
                try:
                    yield session
                finally:
                    await session.close()

            history = EtlRunHistoryRepository(lambda: session_scope())
            assert await history.latest_finished_at(EXTRACTION_ENTRYPOINTS) is None

            async with session_scope() as session:
                for index, (entrypoint, minutes) in enumerate([
                    ("etl_job", 0), ("admin_etl_job", 10),
                    ("sync_business_data", 30), ("admin_sync_business_data", 40),
                ]):
                    at = NOW + timedelta(minutes=minutes)
                    session.add(EtlSyncRun(
                        run_id=f"00000000-0000-4000-8000-00000000000{index}", started_at=at,
                        finished_at=at, entrypoint=entrypoint, allow_shrink=False,
                        debt_synced=True, is_baseline=False,
                    ))
                await session.commit()

            latest = await history.latest_finished_at(EXTRACTION_ENTRYPOINTS)
            assert latest == NOW + timedelta(minutes=10)
            assert latest.utcoffset() == timedelta(hours=7)
            await outer.rollback()
    finally:
        await engine.dispose()
