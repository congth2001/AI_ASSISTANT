"""Authenticated deterministic analytics endpoints for dashboards."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Path, Query, Response, status

from config.container import Container
from src.common.domain.time import now_vietnam
from src.modules.analytics.application.use_cases.customer_debt_history_use_case import (
    CustomerDebtHistoryUseCase,
)
from src.modules.analytics.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.modules.analytics.application.use_cases.export_customer_debt_use_case import (
    ExportCustomerDebtUseCase,
)
from src.modules.analytics.application.use_cases.export_order_ledger_use_case import (
    ExportOrderLedgerUseCase,
)
from src.modules.analytics.domain.models.customer_debt import (
    CustomerDebtExportFilters,
    CustomerDebtSheetMode,
)
from src.modules.analytics.domain.models.customer_debt_history import (
    DebtHistoryEntryFilters,
    DebtHistoryFilters,
    DebtHistoryGrain,
    DebtRevisionFilters,
)
from src.modules.analytics.domain.models.dashboard import (
    DashboardFilters,
    RankingDimension,
    TimeGrain,
)
from src.modules.analytics.domain.models.orders import OrderFilters
from src.modules.analytics.domain.models.order_ledger import OrderLedgerExportFilters
from src.modules.auth.presentation.router import require_role
from src.modules.analytics.presentation.dto.customer_debt_history import (
    CustomerDebtHistoryResponse,
    CustomerDebtRevisionPageResponse,
    DebtHistoryEntryPageResponse,
    DebtRevisionListPageResponse,
)
from src.modules.analytics.presentation.dto.analytics import (
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
    ComparedTimeSeriesPointResponse,
    DataFreshnessResponse,
    OverviewInsightsResponse,
    TimeSeriesComparisonResponse,
)
from src.common.errors import (
    RequestValidationError,
    ValidationError,
)
from src.modules.analytics.domain.errors import (
    FilterValueTooLongError,
    OrderNotFoundError,
    TooManyFilterValuesError,
)

router = APIRouter(prefix="/analytics")

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

MAX_FILTER_VALUES = 100
MAX_FILTER_VALUE_LENGTH = 200


def _bounded_values(values: list | None, name: str) -> tuple:
    """Cap repeated query parameters: at most 100 values of at most 200 characters.

    Raises a catalog validation error; callers convert it to a 422 while building filters.
    """
    items = tuple(values or ())
    if len(items) > MAX_FILTER_VALUES:
        raise TooManyFilterValuesError(name=name, max_values=MAX_FILTER_VALUES)
    if any(isinstance(item, str) and len(item) > MAX_FILTER_VALUE_LENGTH for item in items):
        raise FilterValueTooLongError(name=name, max_length=MAX_FILTER_VALUE_LENGTH)
    return items


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
            ward_names=_bounded_values(ward, "ward"),
            village_names=_bounded_values(village, "village"),
            category_names=_bounded_values(category, "category"),
            product_names=_bounded_values(product, "product"),
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc


async def _execute_validated(call):
    """Await a use case, mapping only catalog *validation* errors (bad cursor, row limit...) to 422.

    Everything else (not found, infrastructure failures) keeps its own status through
    the application error handlers instead of being disguised as a request error.
    """
    try:
        return await call
    except RequestValidationError:
        raise
    except ValidationError as exc:
        raise RequestValidationError(error=exc) from exc


def _period(filters: DashboardFilters) -> AnalyticsPeriodResponse:
    return AnalyticsPeriodResponse(
        date_from=filters.date_from,
        date_to=filters.date_to,
    )


@router.get("/data-freshness", response_model=DataFreshnessResponse)
@inject
async def get_data_freshness(
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(Provide[Container.dashboard_analytics_use_case]),
) -> DataFreshnessResponse:
    """Global latest transaction/record timestamps, not a sync-completion claim."""
    return DataFreshnessResponse.model_validate(await use_case.get_data_freshness())


@router.get("/overview-insights", response_model=OverviewInsightsResponse)
@inject
async def get_overview_insights(
    filters: DashboardFilters = Depends(dashboard_filters),
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(Provide[Container.dashboard_analytics_use_case]),
) -> OverviewInsightsResponse:
    """Customer/geography insights; product/category filters are unsupported."""
    snapshot = await use_case.get_overview_insights(filters)
    return OverviewInsightsResponse(
        period=_period(filters), previous_period=_period(filters.previous_period()),
        **asdict(snapshot),
    )


@router.get("/time-series-comparison", response_model=TimeSeriesComparisonResponse)
@inject
async def get_time_series_comparison(
    grain: Annotated[TimeGrain, Query()] = TimeGrain.DAY,
    filters: DashboardFilters = Depends(dashboard_filters),
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(Provide[Container.dashboard_analytics_use_case]),
) -> TimeSeriesComparisonResponse:
    points = await use_case.get_time_series_comparison(filters, grain)
    return TimeSeriesComparisonResponse(
        period=_period(filters), previous_period=_period(filters.previous_period()),
        grain=grain.value,
        items=[ComparedTimeSeriesPointResponse.model_validate(p) for p in points],
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
    customer_geography: Annotated[bool, Query(description="Filter using current customer geography instead of historical invoice snapshots")] = False,
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
            ward_names=_bounded_values(ward, "ward"),
            village_names=_bounded_values(village, "village"),
            customer_geography=customer_geography,
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
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
            ward_names=_bounded_values(ward, "ward"),
            village_names=_bounded_values(village, "village"),
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    content = await _execute_validated(use_case.execute(filters))
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
        raise OrderNotFoundError()
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
    page = await _execute_validated(
        use_case.get_customer_overview(filters, limit, cursor, offset)
    )
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
            customer_ids=tuple(str(value) for value in _bounded_values(customer_id, "customer_id")),
            ward_names=_bounded_values(ward, "ward"),
            positive_debt_only=positive_debt_only,
            sheet_mode=sheet_mode,
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    content = await _execute_validated(use_case.execute(filters))
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
    category: Annotated[list[str] | None, Query()] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: DashboardAnalyticsUseCase = Depends(
        Provide[Container.dashboard_analytics_use_case]
    ),
) -> AnalyticsFilterOptionsResponse:
    """Filter catalogs; ``ward``/``village`` narrow villages and customers, ``category`` narrows products."""
    try:
        ward_names = _bounded_values(ward, "ward")
        village_names = _bounded_values(village, "village")
        category_names = _bounded_values(category, "category")
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    options = await use_case.get_filter_options(
        search,
        limit,
        ward_names=ward_names,
        village_names=village_names,
        category_names=category_names,
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


# ---------------------------------------------------------------------------
# Customer debt history (docs/customer-debt-history.md, section 5). Unlike the
# dashboard filters above, every date range here is inclusive on both ends.
# ---------------------------------------------------------------------------

DebtSourceType = Literal["opening", "sale", "sales_return", "receipt"]


def _yesterday_vietnam() -> date:
    return now_vietnam().date() - timedelta(days=1)


@router.get(
    "/customers/{customer_id}/debt-history", response_model=CustomerDebtHistoryResponse
)
@inject
async def get_customer_debt_history(
    customer_id: UUID,
    date_from: Annotated[
        date | None, Query(description="Inclusive start day; omit for the whole ledger")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="Inclusive as-of day; defaults to yesterday (Vietnam)")
    ] = None,
    grain: Annotated[DebtHistoryGrain, Query()] = DebtHistoryGrain.MONTH,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: CustomerDebtHistoryUseCase = Depends(
        Provide[Container.customer_debt_history_use_case]
    ),
) -> CustomerDebtHistoryResponse:
    try:
        filters = DebtHistoryFilters(
            date_from=date_from, date_to=date_to or _yesterday_vietnam(), grain=grain
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    history = await _execute_validated(use_case.get_history(str(customer_id), filters))
    return CustomerDebtHistoryResponse.model_validate(history)


@router.get(
    "/customers/{customer_id}/debt-history/entries",
    response_model=DebtHistoryEntryPageResponse,
)
@inject
async def list_customer_debt_entries(
    customer_id: UUID,
    date_from: Annotated[date | None, Query(description="Inclusive start day")] = None,
    date_to: Annotated[date | None, Query(description="Inclusive end day")] = None,
    source_type: Annotated[list[DebtSourceType] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: CustomerDebtHistoryUseCase = Depends(
        Provide[Container.customer_debt_history_use_case]
    ),
) -> DebtHistoryEntryPageResponse:
    try:
        filters = DebtHistoryEntryFilters(
            date_from=date_from,
            date_to=date_to,
            source_types=tuple(dict.fromkeys(source_type or ())),
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    page = await _execute_validated(
        use_case.list_entries(str(customer_id), filters, cursor, limit)
    )
    return DebtHistoryEntryPageResponse.model_validate(page)


@router.get(
    "/customers/{customer_id}/debt-revisions",
    response_model=CustomerDebtRevisionPageResponse,
)
@inject
async def list_customer_debt_revisions(
    customer_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: CustomerDebtHistoryUseCase = Depends(
        Provide[Container.customer_debt_history_use_case]
    ),
) -> CustomerDebtRevisionPageResponse:
    page = await _execute_validated(
        use_case.list_customer_revisions(str(customer_id), cursor, limit)
    )
    return CustomerDebtRevisionPageResponse.model_validate(page)


@router.get("/debt-revisions", response_model=DebtRevisionListPageResponse)
@inject
async def list_debt_revisions(
    date_from: Annotated[date | None, Query(description="Inclusive ETL run day (Vietnam)")] = None,
    date_to: Annotated[date | None, Query(description="Inclusive ETL run day (Vietnam)")] = None,
    ward: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    _current_user: dict = Depends(require_role("staff", "admin")),
    use_case: CustomerDebtHistoryUseCase = Depends(
        Provide[Container.customer_debt_history_use_case]
    ),
) -> DebtRevisionListPageResponse:
    try:
        filters = DebtRevisionFilters(
            date_from=date_from, date_to=date_to, ward_names=_bounded_values(ward, "ward")
        )
    except ValueError as exc:
        raise RequestValidationError(error=exc) from exc
    page = await _execute_validated(use_case.list_revisions(filters, cursor, limit))
    return DebtRevisionListPageResponse.model_validate(page)
