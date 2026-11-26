from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ISalesReturnRepository(ABC):
    @abstractmethod
    async def sync_snapshot(
        self,
        returns: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """Reconcile a complete sales-return header and line snapshot."""
        pass

    @abstractmethod
    async def count_active(self) -> int:
        """Number of rows not soft-deleted; used to guard against shrunken snapshots."""
        pass
