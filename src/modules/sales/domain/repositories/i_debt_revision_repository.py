from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.modules.sales.domain.models.debt_ledger import (
    CustomerDebtRevision,
    DebtTransactionChange,
    EtlSyncRun,
)


class IDebtRevisionRepository(ABC):
    """Audit trail of ETL runs and the retroactive debt changes they made."""

    @abstractmethod
    async def record_run(
        self,
        run: EtlSyncRun,
        changes: Sequence[DebtTransactionChange],
        revisions: Sequence[CustomerDebtRevision],
    ) -> None:
        """Persist the run with its changes; must join the caller's transaction."""
