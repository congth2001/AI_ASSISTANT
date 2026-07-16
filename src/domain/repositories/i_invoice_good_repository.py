from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class IInvoiceGoodRepository(ABC):

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
        category: Optional[str] = None,
        invoice_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def list_categories(self) -> List[str]:
        pass

    @abstractmethod
    async def delete(self, record_id: int) -> bool:
        pass
