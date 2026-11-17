"""Application use case for exporting the order/customer ledger."""

import asyncio

from src.modules.analytics.domain.models.order_ledger import OrderLedgerExportFilters
from src.modules.analytics.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.modules.analytics.domain.ports.i_order_ledger_workbook_exporter import (
    IOrderLedgerWorkbookExporter,
)


class ExportOrderLedgerUseCase:
    def __init__(
        self,
        repository: IDashboardAnalyticsRepository,
        workbook_exporter: IOrderLedgerWorkbookExporter,
    ) -> None:
        self._repository = repository
        self._workbook_exporter = workbook_exporter

    async def execute(self, filters: OrderLedgerExportFilters) -> bytes:
        data = await self._repository.get_order_ledger_export(filters)
        return await asyncio.to_thread(self._workbook_exporter.build, data, filters)
