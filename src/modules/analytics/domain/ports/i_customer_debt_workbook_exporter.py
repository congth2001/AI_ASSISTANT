"""Workbook export contract kept independent from spreadsheet libraries."""

from abc import ABC, abstractmethod

from src.modules.analytics.domain.models.customer_debt import (
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
