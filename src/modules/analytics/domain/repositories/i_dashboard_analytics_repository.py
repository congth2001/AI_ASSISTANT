"""Repository contract for deterministic dashboard queries."""

from abc import ABC, abstractmethod
from src.modules.analytics.domain.models.overview import DataFreshness, OverviewInsightSnapshot

from src.modules.analytics.domain.models.dashboard import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    RankingDimension,
    RankingItem,
    TimeGrain,
    TimeSeriesPoint,
)
from src.modules.analytics.domain.models.customer_debt import (
    CustomerOverviewItem,
    CustomerOverviewCursor,
    CustomerOverviewMetrics,
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
)
from src.modules.analytics.domain.models.orders import (
    OrderDetail,
    OrderFilters,
    OrderSummary,
)
from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)


class IDashboardAnalyticsRepository(ABC):
    @abstractmethod
    async def get_data_freshness(self) -> DataFreshness:
        raise NotImplementedError

    @abstractmethod
    async def get_overview_insights(self, filters: DashboardFilters) -> OverviewInsightSnapshot:
        raise NotImplementedError

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

    @abstractmethod
    async def get_customer_overview(
        self,
        filters: DashboardFilters,
        limit: int,
        cursor: CustomerOverviewCursor | None,
        offset: int = 0,
    ) -> tuple[CustomerOverviewMetrics, list[CustomerOverviewItem], int, bool]:
        raise NotImplementedError

    @abstractmethod
    async def get_customer_debt_export(
        self, filters: CustomerDebtExportFilters
    ) -> list[CustomerDebtExportItem]:
        raise NotImplementedError

    @abstractmethod
    async def list_orders(
        self, filters: OrderFilters, limit: int, offset: int
    ) -> tuple[list[OrderSummary], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_order_detail(self, invoice_id: str) -> OrderDetail | None:
        raise NotImplementedError

    @abstractmethod
    async def get_order_ledger_export(
        self, filters: OrderLedgerExportFilters
    ) -> OrderLedgerExportData:
        raise NotImplementedError
