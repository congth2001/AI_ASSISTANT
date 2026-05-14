from typing import List, Optional, Dict, Any

from src.domain.interfaces.i_data_repository import IDataRepository
from src.infrastructure.persistence.models import BusinessDataModel


class BusinessDataRepository(IDataRepository):
    """SQLAlchemy implementation of business data repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_business_data(self, data_type: str, date_range: Optional['DateRange'] = None) -> List[Dict[str, Any]]:
        """Get business data by type and date range"""
        async with self.session_factory() as session:
            query = BusinessDataModel.__table__.select().where(
                BusinessDataModel.data_type == data_type
            )

            if date_range:
                query = query.where(
                    BusinessDataModel.date >= date_range.start_date,
                    BusinessDataModel.date <= date_range.end_date
                )

            result = await session.execute(query)
            rows = result.all()
            return [dict(row._mapping) for row in rows]

    async def store_business_data(self, data: Dict[str, Any]) -> bool:
        """Store business data"""
        async with self.session_factory() as session:
            business_data = BusinessDataModel(
                id=data['id'],
                data_type=data['data_type'],
                value=data['value'],
                date=data['date'],
                category=data.get('category'),
                subcategory=data.get('subcategory'),
                extra_metadata=data.get('metadata')
            )
            session.add(business_data)
            await session.commit()
            return True

    async def get_customers(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get customer data with optional filters"""
        # Note: This is a simplified implementation
        # In a real system, you'd have a separate CustomerModel
        async with self.session_factory() as session:
            query = BusinessDataModel.__table__.select().where(
                BusinessDataModel.data_type == 'customer'
            )

            if filters:
                if 'segment' in filters:
                    # This would require a proper customer table
                    pass

            result = await session.execute(query)
            rows = result.all()
            return [dict(row._mapping) for row in rows]