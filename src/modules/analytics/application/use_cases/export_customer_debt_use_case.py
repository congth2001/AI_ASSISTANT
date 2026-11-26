"""Export customer receivables to a formatted Excel workbook."""

import asyncio

from src.modules.analytics.domain.models.customer_debt import CustomerDebtExportFilters
from src.modules.analytics.domain.repositories.i_customer_debt_export_repository import (
    ICustomerDebtExportRepository,
)
from src.modules.analytics.domain.ports.i_customer_debt_workbook_exporter import (
    ICustomerDebtWorkbookExporter,
)


class ExportCustomerDebtUseCase:
    def __init__(
        self,
        repository: ICustomerDebtExportRepository,
        workbook_exporter: ICustomerDebtWorkbookExporter,
    ):
        self._repository = repository
        self._workbook_exporter = workbook_exporter

    async def execute(self, filters: CustomerDebtExportFilters) -> bytes:
        items = await self._repository.get_customer_debt_export(filters)
        return await asyncio.to_thread(self._workbook_exporter.build, items, filters)
