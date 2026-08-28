"""Application orchestration for dashboard analytics."""

import base64
import binascii
import json
from decimal import Decimal, ROUND_HALF_UP

from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardSummary,
    CustomerOverviewPage,
    CustomerOverviewCursor,
    RankingDimension,
    RankingPage,
    TimeGrain,
    TimeSeriesPoint,
)
from src.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)


class DashboardAnalyticsUseCase:
    def __init__(self, repository: IDashboardAnalyticsRepository):
        self._repository = repository

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
        self, filters: DashboardFilters, limit: int, cursor: str | None
    ) -> CustomerOverviewPage:
        decoded_cursor = self._decode_customer_cursor(cursor) if cursor else None
        metrics, items, total, has_more = await self._repository.get_customer_overview(
            filters, limit, decoded_cursor
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
                raise ValueError("Invalid cursor values")
            return cursor
        except (binascii.Error, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid customer overview cursor") from exc
