"""Application orchestration for dashboard analytics."""

import base64
import binascii
import json
from decimal import Decimal
from uuid import UUID

from src.modules.analytics.domain.models.dashboard import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardSummary,
    RankingDimension,
    RankingPage,
    TimeGrain,
    TimeSeriesPoint,
)
from src.modules.analytics.domain.models.customer_debt import (
    CustomerOverviewPage,
    CustomerOverviewCursor,
)
from src.modules.analytics.domain.models.overview import (
    ComparedTimeSeriesPoint, DataFreshness, OverviewInsightSnapshot,
)
from src.modules.analytics.domain.models.orders import (
    OrderDetail,
    OrderFilters,
    OrderPage,
)
from src.modules.analytics.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.modules.analytics.domain.services.period_comparison import (
    align_period_series,
    summarize_periods,
)
from src.modules.analytics.domain.errors import (
    CursorPaginationConflictError,
    InvalidCursorValuesError,
    InvalidCustomerOverviewCursorError,
    OverviewDimensionsUnsupportedError,
)


class DashboardAnalyticsUseCase:
    def __init__(self, repository: IDashboardAnalyticsRepository):
        self._repository = repository

    async def get_data_freshness(self) -> DataFreshness:
        return await self._repository.get_data_freshness()

    async def get_overview_insights(self, filters: DashboardFilters) -> OverviewInsightSnapshot:
        if filters.category_names or filters.product_names:
            raise OverviewDimensionsUnsupportedError()
        return await self._repository.get_overview_insights(filters)

    async def get_time_series_comparison(
        self, filters: DashboardFilters, grain: TimeGrain,
    ) -> list[ComparedTimeSeriesPoint]:
        """Two equal-length periods aligned by day offset (see ``align_period_series``)."""
        current = await self._repository.get_time_series(filters, TimeGrain.DAY)
        previous = await self._repository.get_time_series(filters.previous_period(), TimeGrain.DAY)
        return align_period_series(filters, grain, current, previous)

    async def get_summary(self, filters: DashboardFilters) -> DashboardSummary:
        current = await self._repository.get_metric_snapshot(filters)
        previous = await self._repository.get_metric_snapshot(filters.previous_period())
        return summarize_periods(current, previous)

    async def get_time_series(
        self, filters: DashboardFilters, grain: TimeGrain
    ) -> list[TimeSeriesPoint]:
        return await self._repository.get_time_series(filters, grain)

    async def get_ranking(
        self,
        filters: DashboardFilters,
        dimension: RankingDimension,
        limit: int,
        offset: int,
    ) -> RankingPage:
        items, total = await self._repository.get_ranking(
            filters, dimension, limit, offset
        )
        return RankingPage(
            dimension=dimension,
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_filter_options(
        self,
        search: str | None,
        limit: int,
        ward_names: tuple[str, ...] = (),
        village_names: tuple[str, ...] = (),
        category_names: tuple[str, ...] = (),
    ) -> DashboardFilterOptions:
        normalized_search = search.strip() if search and search.strip() else None
        return await self._repository.get_filter_options(
            normalized_search,
            limit,
            ward_names=ward_names,
            village_names=village_names,
            category_names=category_names,
        )

    async def get_customer_overview(
        self,
        filters: DashboardFilters,
        limit: int,
        cursor: str | None,
        offset: int = 0,
    ) -> CustomerOverviewPage:
        if cursor and offset:
            raise CursorPaginationConflictError()
        decoded_cursor = self._decode_customer_cursor(cursor) if cursor else None
        metrics, items, total, has_more = await self._repository.get_customer_overview(
            filters, limit, decoded_cursor, offset
        )
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = self._encode_customer_cursor(
                CustomerOverviewCursor(
                    current_debt=last.current_debt,
                    revenue=last.revenue,
                    label=last.label,
                    key=last.key,
                )
            )
        return CustomerOverviewPage(
            metrics=metrics,
            items=tuple(items),
            total=total,
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def list_orders(
        self, filters: OrderFilters, limit: int, offset: int
    ) -> OrderPage:
        items, total = await self._repository.list_orders(filters, limit, offset)
        return OrderPage(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_order_detail(self, invoice_id: str) -> OrderDetail | None:
        return await self._repository.get_order_detail(invoice_id)

    @staticmethod
    def _encode_customer_cursor(cursor: CustomerOverviewCursor) -> str:
        payload = json.dumps(
            {
                "debt": str(cursor.current_debt),
                "revenue": str(cursor.revenue),
                "label": cursor.label,
                "key": cursor.key,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_customer_cursor(value: str) -> CustomerOverviewCursor:
        """Decode and strictly validate an opaque cursor; any malformed input is a 422.

        ``Decimal(...)`` raises ``decimal.InvalidOperation`` (an ``ArithmeticError``) and
        a non-UUID key would crash the database driver later, so both are checked here.
        """
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if not isinstance(payload, dict):
                raise InvalidCustomerOverviewCursorError()
            debt, revenue = payload["debt"], payload["revenue"]
            label, key = payload["label"], payload["key"]
            if not all(isinstance(item, str) for item in (debt, revenue, label, key)):
                raise InvalidCustomerOverviewCursorError()
            cursor = CustomerOverviewCursor(
                current_debt=Decimal(debt),
                revenue=Decimal(revenue),
                label=label,
                key=str(UUID(key)),
            )
        except InvalidCustomerOverviewCursorError:
            raise
        except (binascii.Error, KeyError, TypeError, ValueError, ArithmeticError, RecursionError) as exc:
            raise InvalidCustomerOverviewCursorError() from exc
        if (
            not _is_reasonable_amount(cursor.current_debt)
            or not _is_reasonable_amount(cursor.revenue)
            or not cursor.label
        ):
            raise InvalidCursorValuesError()
        return cursor


# Money columns are numeric(18, 2); anything beyond this cannot come from our own cursor.
_MAX_CURSOR_AMOUNT = Decimal(10) ** 18


def _is_reasonable_amount(value: Decimal) -> bool:
    # Also bounds the scale so the driver never receives an absurd numeric.
    return (
        value.is_finite()
        and abs(value) < _MAX_CURSOR_AMOUNT
        and int(value.as_tuple().exponent) >= -6
    )
