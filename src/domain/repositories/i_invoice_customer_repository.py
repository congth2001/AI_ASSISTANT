from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime


class IInvoiceCustomerRepository(ABC):

    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_by_invoice_id(self, invoice_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def list(
        self,
        name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def delete(self, record_id: int) -> bool:
        pass
