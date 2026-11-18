from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ICustomerDebtTransactionRepository(ABC):
    @abstractmethod
    async def sync_snapshot(self, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        """Reconcile the complete source debt ledger snapshot."""
        pass

    @abstractmethod
    async def count_active(self) -> int:
        """Number of rows not soft-deleted; used to guard against shrunken snapshots."""
        pass
