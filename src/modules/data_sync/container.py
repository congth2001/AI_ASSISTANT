"""Dependency wiring owned by the data_sync module."""
from dependency_injector import containers
from dependency_injector.providers import Configuration, Dependency, Singleton

from src.modules.data_sync.application.use_cases.data_sync_use_case import DataSyncUseCase
from src.modules.data_sync.infrastructure.repositories.etl_run_history_repository import (
    EtlRunHistoryRepository,
)
from src.modules.data_sync.infrastructure.repositories.sync_job_repository import (
    SyncJobRepository,
)
from src.modules.data_sync.infrastructure.runners.subprocess_sync_runner import (
    SubprocessSyncRunner,
)


class DataSyncContainer(containers.DeclarativeContainer):
    config = Configuration()
    session_factory = Dependency()
    # backend/ directory: the worker runs from there like the ETL CLIs.
    backend_dir = Dependency()

    sync_job_repository = Singleton(SyncJobRepository, session_factory=session_factory)
    etl_run_history = Singleton(EtlRunHistoryRepository, session_factory=session_factory)

    sync_runner = Singleton(
        SubprocessSyncRunner,
        backend_dir=backend_dir,
        mdb_source_path=config.etl.source_path.as_(lambda value: value or ""),
        snapshot_dir=config.etl.snapshot_dir.as_(lambda value: value or "data/documents"),
    )

    data_sync_use_case = Singleton(
        DataSyncUseCase,
        repository=sync_job_repository,
        runner=sync_runner,
        run_history=etl_run_history,
        timeout_seconds=config.etl.job_timeout_seconds.as_(lambda value: int(value or 3600)),
    )
