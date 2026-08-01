from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ICustomerRepository(ABC):
    @abstractmethod
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_by_id(self, customer_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_by_identity_key(self, identity_key: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def upsert_many(self, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        """Upsert customers and return identity_key -> customer_id."""
        pass

    @abstractmethod
    async def list(
        self,
        name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def delete(self, customer_id: str) -> bool:
        pass
