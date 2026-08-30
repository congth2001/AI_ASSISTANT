"""Workbook export contract kept independent from spreadsheet libraries."""

from abc import ABC, abstractmethod

from src.domain.entities.dashboard_analytics import (
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
)


class ICustomerDebtWorkbookExporter(ABC):
    @abstractmethod
    def build(
        self,
        items: list[CustomerDebtExportItem],
        filters: CustomerDebtExportFilters,
    ) -> bytes:
        raise NotImplementedError
