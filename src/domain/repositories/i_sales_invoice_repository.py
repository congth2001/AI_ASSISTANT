from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional


class ISalesInvoiceRepository(ABC):
    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_by_id(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_by_invoice_number(
        self, invoice_number: str
    ) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def upsert_many(self, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        """Upsert invoices and return invoice_number -> invoice_id."""
        pass

    @abstractmethod
    async def list(
        self,
        customer_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def delete(self, invoice_id: str) -> bool:
        pass
