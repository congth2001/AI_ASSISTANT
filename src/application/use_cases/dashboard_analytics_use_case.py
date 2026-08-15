"""Application orchestration for dashboard analytics."""

from decimal import Decimal, ROUND_HALF_UP

from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardSummary,
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
