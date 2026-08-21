from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ICustomerDebtTransactionRepository(ABC):
    @abstractmethod
    async def sync_snapshot(self, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        """Reconcile the complete source debt ledger snapshot."""
        pass
