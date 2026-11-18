"""Narrow port for the customer-debt export use case."""

from abc import ABC, abstractmethod

from src.modules.analytics.domain.models.customer_debt import (
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
)


class ICustomerDebtExportRepository(ABC):
    @abstractmethod
    async def get_customer_debt_export(
        self, filters: CustomerDebtExportFilters
    ) -> list[CustomerDebtExportItem]:
        raise NotImplementedError
