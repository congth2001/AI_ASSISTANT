"""Admin endpoints to run the business-data sync and read its history."""
import logging
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, status

from config.container import Container
from src.common.errors import ApplicationError
from src.modules.auth.presentation.router import require_role
from src.modules.data_sync.application.use_cases.data_sync_use_case import DataSyncUseCase
from src.modules.data_sync.domain.errors import SyncJobReadFailedError, SyncJobStartFailedError
from src.modules.data_sync.domain.repositories.i_sync_job_repository import (
    MAX_SYNC_JOB_PAGE_SIZE,
)
from src.modules.data_sync.presentation.dto.data_sync import (
    DataSyncStatusResponse,
    StartSyncJobRequest,
    SyncJobPageResponse,
    SyncJobResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-sync")
require_admin = require_role("admin")


@router.get("/status", response_model=DataSyncStatusResponse)
@inject
async def get_status(
    _admin: dict = Depends(require_admin),
    use_case: DataSyncUseCase = Depends(Provide[Container.data_sync_use_case]),
) -> DataSyncStatusResponse:
    try:
        return DataSyncStatusResponse.model_validate(await use_case.get_status())
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to read data sync status")
        raise SyncJobReadFailedError() from exc


@router.get("/jobs", response_model=SyncJobPageResponse)
@inject
async def list_jobs(
    limit: int = Query(20, ge=1, le=MAX_SYNC_JOB_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_admin),
    use_case: DataSyncUseCase = Depends(Provide[Container.data_sync_use_case]),
) -> SyncJobPageResponse:
    try:
        page = await use_case.list_jobs(limit, offset)
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to list data sync jobs")
        raise SyncJobReadFailedError() from exc
    return SyncJobPageResponse(
        items=[SyncJobResponse.model_validate(job) for job in page.items],
        has_more=page.has_more,
    )


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
@inject
async def get_job(
    job_id: UUID,
    _admin: dict = Depends(require_admin),
    use_case: DataSyncUseCase = Depends(Provide[Container.data_sync_use_case]),
) -> SyncJobResponse:
    try:
        return SyncJobResponse.model_validate(await use_case.get_job(str(job_id)))
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to read data sync job %s", job_id)
        raise SyncJobReadFailedError() from exc


@router.post("/jobs", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
@inject
async def start_job(
    request: StartSyncJobRequest,
    admin: dict = Depends(require_admin),
    use_case: DataSyncUseCase = Depends(Provide[Container.data_sync_use_case]),
) -> SyncJobResponse:
    """Start a sync in the background; poll ``GET /data-sync/jobs/{id}`` for the outcome."""
    try:
        job = await use_case.start(
            request.source,
            allow_shrink=request.allow_shrink,
            triggered_by_id=admin["id"],
            allow_stale_snapshot=request.allow_stale_snapshot,
        )
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to start a data sync job")
        raise SyncJobStartFailedError() from exc
    return SyncJobResponse.model_validate(job)
