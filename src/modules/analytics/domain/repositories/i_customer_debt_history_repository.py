"""Narrow port for the customer debt-history page and its revision audit trail."""
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from src.modules.analytics.domain.models.customer_debt_history import (
    CustomerDebtProfile,
    CustomerDebtRevisionItem,
    DebtHistoryEntry,
    DebtHistoryEntryCursor,
    DebtHistoryEntryFilters,
    DebtLedgerEntry,
    DebtRevisionFilters,
    DebtRevisionListItem,
    DebtRevisionSummary,
    LatestSyncRun,
    RunCursor,
)


class ICustomerDebtHistoryRepository(ABC):
    @abstractmethod
    async def get_customer_profile(self, customer_id: str) -> CustomerDebtProfile | None:
        """Active (not soft-deleted) customer, or None."""

    @abstractmethod
    async def list_ledger_entries(
        self, customer_id: str, until: datetime, limit: int
    ) -> list[DebtLedgerEntry]:
        """Active entries with ``occurred_at < until`` in ledger order, at most ``limit``."""

    @abstractmethod
    async def get_current_balance(self, customer_id: str) -> Decimal:
        """Sum of every active entry, whatever the date."""

    @abstractmethod
    async def get_revision_summary(self, customer_id: str) -> DebtRevisionSummary:
        """Number of runs that revised the customer, and the latest one."""

    @abstractmethod
    async def list_entry_page(
        self,
        customer_id: str,
        filters: DebtHistoryEntryFilters,
        cursor: DebtHistoryEntryCursor | None,
        limit: int,
    ) -> tuple[list[tuple[DebtHistoryEntry, DebtHistoryEntryCursor]], bool]:
        """Newest-first entries after ``cursor`` with each row's own cursor, and ``has_more``."""

    @abstractmethod
    async def list_customer_revisions(
        self, customer_id: str, cursor: RunCursor | None, limit: int, max_changes: int
    ) -> tuple[list[CustomerDebtRevisionItem], bool]:
        """Newest-first runs that revised the customer, and ``has_more``."""

    @abstractmethod
    async def list_debt_revisions(
        self, filters: DebtRevisionFilters, cursor: RunCursor | None, limit: int
    ) -> tuple[LatestSyncRun | None, list[DebtRevisionListItem], bool]:
        """Latest run summary plus newest-first per-customer revisions, and ``has_more``."""
