from abc import ABC, abstractmethod

from src.modules.sales.domain.models.debt_ledger import DebtLedgerRow, DebtSnapshotDiff


class ICustomerDebtTransactionRepository(ABC):
    @abstractmethod
    async def load_ledger_state(self) -> list[DebtLedgerRow]:
        """Every stored ledger row, soft-deleted ones included (``deleted=True``)."""

    @abstractmethod
    async def apply_diff(self, diff: DebtSnapshotDiff) -> None:
        """Insert, update, restore and soft delete exactly the rows named in ``diff``.

        Unchanged rows are not touched, so their ``updated_at`` keeps meaning
        "last real change".
        """

    @abstractmethod
    async def count_active(self) -> int:
        """Number of rows not soft-deleted; used to guard against shrunken snapshots."""
