"""Authenticated deterministic analytics endpoints for dashboards."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from config.container import Container
from src.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.application.use_cases.export_customer_debt_use_case import (
    ExportCustomerDebtUseCase,
)
from src.application.use_cases.export_order_ledger_use_case import (
    ExportOrderLedgerUseCase,
)
from src.domain.entities.dashboard_analytics import (
    CustomerDebtExportFilters,
    CustomerDebtSheetMode,
    DashboardFilters,
    OrderFilters,
    OrderLedgerExportFilters,
    RankingDimension,
    TimeGrain,
)
from src.presentation.api.v1.auth import require_role
from src.presentation.dto.analytics import (
    AnalyticsFilterOptionsResponse,
    AnalyticsPeriodResponse,
    AnalyticsSummaryResponse,
    CustomerOverviewItemResponse,
    CustomerOverviewMetricsResponse,
    CustomerOverviewResponse,
    FilterOptionResponse,
    MetricSnapshotResponse,
    OrderDetailResponse,
    OrderPageResponse,
    OrderSummaryResponse,
    RankingItemResponse,
    RankingResponse,
    RevenueComparisonResponse,
    TimeSeriesPointResponse,
    TimeSeriesResponse,
)

router = APIRouter(prefix="/analytics")

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dashboard_filters(
    date_from: Annotated[
        date, Query(description="Inclusive start date in Vietnam business time")
    ],
    date_to: Annotated[
        date, Query(description="Exclusive end date in Vietnam business time")
    ],
    customer_id: Annotated[UUID | None, Query()] = None,
    ward: Annotated[list[str] | None, Query()] = None,
    village: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    product: Annotated[list[str] | None, Query()] = None,
) -> DashboardFilters:
    try:
        return DashboardFilters(
            date_from=date_from,
            date_to=date_to,
            customer_id=str(customer_id) if customer_id else None,
            ward_names=tuple(ward or ()),
            village_names=tuple(village or ()),
            category_names=tuple(category or ()),
            product_names=tuple(product or ()),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _period(filters: DashboardFilters) -> AnalyticsPeriodResponse:
    return AnalyticsPeriodResponse(
        date_from=filters.date_from,
        date_to=filters.date_to,
    )


@router.get("/orders", response_model=OrderPageResponse)
@inject
async def list_orders(
    date_from: Annotated[date | None, Query(description="Inclusive start date")] = None,
    date_to: Annotated[date | None, Query(description="Exclusive end date")] = None,
    invoice_number: Annotated[str | None, Query(max_length=100)] = None,
    customer_id: Annotated[UUID | None, Query()] = None,
    ward: Annotated[list[str] | None, Query()] = None,
    village: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> OrderPageResponse:
    try:
        filters = OrderFilters(
            date_from=date_from,
            date_to=date_to,
            invoice_number=(
                invoice_number.strip()
                if invoice_number and invoice_number.strip()
                else None
            ),
            customer_id=str(customer_id) if customer_id else None,
            ward_names=tuple(ward or ()),
            village_names=tuple(village or ()),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    page = await use_case.list_orders(filters, limit, offset)
    return OrderPageResponse(
        items=[OrderSummaryResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/orders/export")
@inject
async def export_order_ledger(
    customer_id: Annotated[UUID, Query()],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    invoice_number: Annotated[str | None, Query(max_length=100)] = None,
    ward: Annotated[list[str] | None, Query()] = None,
    village: Annotated[list[str] | None, Query()] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: ExportOrderLedgerUseCase = Depends(
        Provide[Container.export_order_ledger_use_case]
    ),
) -> Response:
    try:
        filters = OrderLedgerExportFilters(
            date_from=date_from,
            date_to=date_to,
            invoice_number=(
                invoice_number.strip()
                if invoice_number and invoice_number.strip()
                else None
            ),
            customer_id=str(customer_id),
            ward_names=tuple(ward or ()),
            village_names=tuple(village or ()),
        )
        content = await use_case.execute(filters)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    filename = f"chi-tiet-giao-dich-cong-no-{datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y%m%d-%H%M%S')}.xlsx"
    return Response(
        content=content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/orders/{invoice_id}", response_model=OrderDetailResponse)
@inject
async def get_order_detail(
    invoice_id: Annotated[str, Path(min_length=1, max_length=200)],
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> OrderDetailResponse:
    order = await use_case.get_order_detail(invoice_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderDetailResponse.model_validate(order)


@router.get("/customer-overview", response_model=CustomerOverviewResponse)
@inject
async def get_customer_overview(
    filters: DashboardFilters = Depends(dashboard_filters),
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> CustomerOverviewResponse:
    try:
        page = await use_case.get_customer_overview(filters, limit, cursor, offset)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return CustomerOverviewResponse(
        period=_period(filters),
        metrics=CustomerOverviewMetricsResponse.model_validate(page.metrics),
        items=[
            CustomerOverviewItemResponse.model_validate(item) for item in page.items
        ],
        total=page.total,
        limit=page.limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/customer-debt/export")
@inject
async def export_customer_debt(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    customer_id: Annotated[list[UUID] | None, Query()] = None,
    ward: Annotated[list[str] | None, Query()] = None,
    positive_debt_only: Annotated[bool, Query()] = False,
    sheet_mode: Annotated[CustomerDebtSheetMode, Query()] = CustomerDebtSheetMode.SINGLE,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: ExportCustomerDebtUseCase = Depends(
        Provide[Container.export_customer_debt_use_case]
    ),
) -> Response:
    try:
        filters = CustomerDebtExportFilters(
            date_from=date_from,
            date_to=date_to,
            customer_ids=tuple(str(value) for value in customer_id or ()),
            ward_names=tuple(ward or ()),
            positive_debt_only=positive_debt_only,
            sheet_mode=sheet_mode,
        )
        content = await use_case.execute(filters)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    filename = f"cong-no-khach-hang-{datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%Y%m%d-%H%M%S')}.xlsx"
    return Response(
        content=content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/summary", response_model=AnalyticsSummaryResponse)
@inject
async def get_summary(
    filters: DashboardFilters = Depends(dashboard_filters),
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> AnalyticsSummaryResponse:
    summary = await use_case.get_summary(filters)
    return AnalyticsSummaryResponse(
        period=_period(filters),
        metrics=MetricSnapshotResponse.model_validate(summary.current),
        comparison=RevenueComparisonResponse(
            previous_revenue=summary.previous_revenue,
            revenue_change=summary.revenue_change,
            revenue_growth_percent=summary.revenue_growth_percent,
        ),
    )


@router.get("/time-series", response_model=TimeSeriesResponse)
@inject
async def get_time_series(
    grain: Annotated[TimeGrain, Query()] = TimeGrain.DAY,
    filters: DashboardFilters = Depends(dashboard_filters),
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> TimeSeriesResponse:
    points = await use_case.get_time_series(filters, grain)
    return TimeSeriesResponse(
        period=_period(filters),
        grain=grain.value,
        items=[TimeSeriesPointResponse.model_validate(point) for point in points],
    )


@router.get("/rankings/{dimension}", response_model=RankingResponse)
@inject
async def get_ranking(
    dimension: Annotated[RankingDimension, Path()],
    filters: DashboardFilters = Depends(dashboard_filters),
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> RankingResponse:
    page = await use_case.get_ranking(filters, dimension, limit, offset)
    return RankingResponse(
        period=_period(filters),
        dimension=dimension.value,
        items=[RankingItemResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/filter-options", response_model=AnalyticsFilterOptionsResponse)
@inject
async def get_filter_options(
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ward: Annotated[list[str] | None, Query()] = None,
    village: Annotated[list[str] | None, Query()] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> AnalyticsFilterOptionsResponse:
    options = await use_case.get_filter_options(
        search,
        limit,
        ward_names=tuple(ward or ()),
        village_names=tuple(village or ()),
    )
    return AnalyticsFilterOptionsResponse(
        customers=[
            FilterOptionResponse.model_validate(item) for item in options.customers
        ],
        wards=list(options.wards),
        villages=list(options.villages),
        categories=list(options.categories),
        products=list(options.products),
    )
