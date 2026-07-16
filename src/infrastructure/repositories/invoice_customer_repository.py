from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select, update
from uuid import UUID, uuid4
from src.domain.repositories.i_invoice_customer_repository import IInvoiceCustomerRepository
from src.infrastructure.repositories.models import InvoiceCustomer


class InvoiceCustomerRepository(IInvoiceCustomerRepository):
    """SQLAlchemy implementation of invoice customer repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new invoice customer record"""
        async with self.session_factory() as session:
            customer = InvoiceCustomer(
                id=str(uuid4()),
                invoice_id=data["invoice_id"],
                date=data["date"],
                name=data["name"],
                address_detail=data.get("address_detail"),
                address_village=data.get("address_village"),
                address_ward=data.get("address_ward"),
                total_amount=data["total_amount"],
                debt_amount=data.get("debt_amount"),
            )
            session.add(customer)
            await session.commit()
            await session.refresh(customer)
            return customer.__dict__

    async def get_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Get a single invoice customer by primary key"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(InvoiceCustomer).where(
                    InvoiceCustomer.id == record_id,
                    InvoiceCustomer.deleted_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            return row.__dict__ if row else None

    async def get_by_invoice_id(self, invoice_id: str) -> List[Dict[str, Any]]:
        """Get all customer records for a given invoice ID"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(InvoiceCustomer).where(
                    InvoiceCustomer.invoice_id == invoice_id,
                    InvoiceCustomer.deleted_at.is_(None),
                )
            )
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]

    async def list(
        self,
        name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List invoice customers with optional filters"""
        async with self.session_factory() as session:
            stmt = select(InvoiceCustomer).where(InvoiceCustomer.deleted_at.is_(None))

            if name:
                stmt = stmt.where(InvoiceCustomer.name.ilike(f"%{name}%"))
            if date_from:
                stmt = stmt.where(InvoiceCustomer.date >= date_from)
            if date_to:
                stmt = stmt.where(InvoiceCustomer.date <= date_to)

            stmt = stmt.order_by(InvoiceCustomer.date.desc()).limit(limit).offset(offset)

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]

    async def delete(self, record_id: int) -> bool:
        """Soft-delete an invoice customer record"""
        async with self.session_factory() as session:
            result = await session.execute(
                update(InvoiceCustomer)
                .where(
                    InvoiceCustomer.id == record_id,
                    InvoiceCustomer.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.utcnow())
            )
            await session.commit()
            return result.rowcount > 0
