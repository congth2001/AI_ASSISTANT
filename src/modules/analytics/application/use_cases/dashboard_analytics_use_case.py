"""Application orchestration for dashboard analytics."""

import base64
import binascii
import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

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
        """Align equal-length periods by day offset, then bucket by current dates.

        Calendar months/weeks may have different lengths and boundaries. Bucketing
        both periods independently would compare different numbers of days.
        """
        current = {p.period_start: p for p in await self._repository.get_time_series(filters, TimeGrain.DAY)}
        previous_filters = filters.previous_period()
        previous = {p.period_start: p for p in await self._repository.get_time_series(previous_filters, TimeGrain.DAY)}
        buckets: dict[date, ComparedTimeSeriesPoint] = {}
        for offset in range(filters.day_count):
            day = filters.date_from + timedelta(days=offset)
            previous_day = previous_filters.date_from + timedelta(days=offset)
            if grain == TimeGrain.WEEK:
                key = day - timedelta(days=day.weekday())
            elif grain == TimeGrain.MONTH:
                key = day.replace(day=1)
            elif grain == TimeGrain.QUARTER:
                key = day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
            elif grain == TimeGrain.YEAR:
                key = day.replace(month=1, day=1)
            else:
                key = day
            if key not in buckets:
                buckets[key] = ComparedTimeSeriesPoint(
                    day, day, previous_day, previous_day, Decimal(0), Decimal(0), 0, 0,
                )
            bucket = buckets[key]
            current_point, previous_point = current.get(day), previous.get(previous_day)
            buckets[key] = replace(
                bucket,
                period_end=day + timedelta(days=1),
                previous_period_end=previous_day + timedelta(days=1),
                revenue=bucket.revenue + (current_point.revenue if current_point else Decimal(0)),
                previous_revenue=bucket.previous_revenue + (previous_point.revenue if previous_point else Decimal(0)),
                invoice_count=bucket.invoice_count + (current_point.invoice_count if current_point else 0),
                previous_invoice_count=bucket.previous_invoice_count + (previous_point.invoice_count if previous_point else 0),
            )
        return list(buckets.values())

    async def get_summary(self, filters: DashboardFilters) -> DashboardSummary:
        current = await self._repository.get_metric_snapshot(filters)
        previous = await self._repository.get_metric_snapshot(
            filters.previous_period()
        )
        change = current.total_revenue - previous.total_revenue
        growth = None
        if previous.total_revenue != 0:
            growth = (
                change * Decimal("100") / previous.total_revenue
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return DashboardSummary(
            current=current,
            previous_revenue=previous.total_revenue,
            revenue_change=change,
            revenue_growth_percent=growth,
        )

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
    ) -> DashboardFilterOptions:
        normalized_search = search.strip() if search and search.strip() else None
        return await self._repository.get_filter_options(
            normalized_search,
            limit,
            ward_names=ward_names,
            village_names=village_names,
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
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            cursor = CustomerOverviewCursor(
                current_debt=Decimal(payload["debt"]),
                revenue=Decimal(payload["revenue"]),
                label=str(payload["label"]),
                key=str(payload["key"]),
            )
            if (
                not cursor.current_debt.is_finite()
                or not cursor.revenue.is_finite()
                or not cursor.label
                or not cursor.key
            ):
                raise InvalidCursorValuesError()
            return cursor
        except (binascii.Error, KeyError, TypeError, ValueError) as exc:
            raise InvalidCustomerOverviewCursorError() from exc
