from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ISalesInvoiceLineRepository(ABC):
    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_by_id(self, invoice_line_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_by_invoice_id(self, invoice_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def upsert_snapshot(
        self,
        rows: List[Dict[str, Any]],
        invoice_ids: List[str],
    ) -> int:
        """Reconcile a full line snapshot for the supplied invoices."""
        pass

    @abstractmethod
    async def list(
        self,
        product_name: Optional[str] = None,
        category_name: Optional[str] = None,
        invoice_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def list_categories(self) -> List[str]:
        pass

    @abstractmethod
    async def delete(self, invoice_line_id: str) -> bool:
        pass
