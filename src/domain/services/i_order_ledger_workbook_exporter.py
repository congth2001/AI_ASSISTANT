"""Workbook port for the order/customer ledger export."""

from abc import ABC, abstractmethod

from src.domain.entities.dashboard_analytics import (
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
