"""Repository contract for deterministic dashboard queries."""

from abc import ABC, abstractmethod

from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    RankingDimension,
    RankingItem,
    TimeGrain,
    TimeSeriesPoint,
)


class IDashboardAnalyticsRepository(ABC):
    @abstractmethod
    async def get_metric_snapshot(
        self, filters: DashboardFilters
    ) -> DashboardMetricSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def get_time_series(
        self, filters: DashboardFilters, grain: TimeGrain
    ) -> list[TimeSeriesPoint]:
        raise NotImplementedError

    @abstractmethod
    async def get_ranking(
        self,
        filters: DashboardFilters,
        dimension: RankingDimension,
        limit: int,
        offset: int,
    ) -> tuple[list[RankingItem], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_filter_options(
        self,
        search: str | None,
        limit: int,
        ward_names: tuple[str, ...] = (),
        village_names: tuple[str, ...] = (),
    ) -> DashboardFilterOptions:
        raise NotImplementedError
