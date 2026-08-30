"""Export customer receivables to a formatted Excel workbook."""

import asyncio

from src.domain.entities.dashboard_analytics import CustomerDebtExportFilters
from src.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.domain.services.i_customer_debt_workbook_exporter import (
    ICustomerDebtWorkbookExporter,
)


class ExportCustomerDebtUseCase:
    def __init__(
        self,
        repository: IDashboardAnalyticsRepository,
        workbook_exporter: ICustomerDebtWorkbookExporter,
    ):
        self._repository = repository
        self._workbook_exporter = workbook_exporter

    async def execute(self, filters: CustomerDebtExportFilters) -> bytes:
        items = await self._repository.get_customer_debt_export(filters)
        return await asyncio.to_thread(self._workbook_exporter.build, items, filters)
