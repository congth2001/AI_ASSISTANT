"""Workbook port for the order/customer ledger export."""

from abc import ABC, abstractmethod

from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)


class IOrderLedgerWorkbookExporter(ABC):
    @abstractmethod
    def build(
        self,
        data: OrderLedgerExportData,
        filters: OrderLedgerExportFilters,
    ) -> bytes:
        raise NotImplementedError
