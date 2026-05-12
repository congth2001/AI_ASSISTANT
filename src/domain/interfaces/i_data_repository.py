from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class IDataRepository(ABC):
    """Interface for data repository operations"""

    @abstractmethod
    async def get_business_data(self, data_type: str, date_range: Optional['DateRange'] = None) -> List[Dict[str, Any]]:
        """Get business data by type and date range"""
        pass

    @abstractmethod
    async def store_business_data(self, data: Dict[str, Any]) -> bool:
        """Store business data"""
        pass

    @abstractmethod
    async def get_customers(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get customer data with optional filters"""
        pass