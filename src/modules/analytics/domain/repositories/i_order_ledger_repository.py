"""Narrow port for the order-ledger export use case."""

from abc import ABC, abstractmethod

from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)


class IOrderLedgerRepository(ABC):
    @abstractmethod
    async def get_order_ledger_export(
        self, filters: OrderLedgerExportFilters
    ) -> OrderLedgerExportData:
        raise NotImplementedError
