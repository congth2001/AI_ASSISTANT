from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update, distinct
from src.domain.repositories.i_invoice_good_repository import IInvoiceGoodRepository
from src.infrastructure.repositories.models import InvoiceGood


class InvoiceGoodRepository(IInvoiceGoodRepository):
    """SQLAlchemy implementation of invoice good repository"""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new invoice good record"""
        async with self.session_factory() as session:
            good = InvoiceGood(
                id=str(uuid4()),
                invoice_id=data["invoice_id"],
                name=data["name"],
                category=data.get("category"),
                unit_type=data["unit_type"],
                unit_price=data["unit_price"],
                quantity=data["quantity"],
                total_price=data["total_price"],
            )
            session.add(good)
            await session.commit()
            await session.refresh(good)
            return good.__dict__

    async def get_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Get a single invoice good by primary key"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(InvoiceGood).where(
                    InvoiceGood.id == record_id,
                    InvoiceGood.deleted_at.is_(None),
                )
            )
            row = result.scalar_one_or_none()
            return row.__dict__ if row else None

    async def get_by_invoice_id(self, invoice_id: str) -> List[Dict[str, Any]]:
        """Get all goods for a given invoice ID"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(InvoiceGood).where(
                    InvoiceGood.invoice_id == invoice_id,
                    InvoiceGood.deleted_at.is_(None),
                )
            )
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]

    async def list(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None,
        invoice_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List invoice goods with optional filters"""
        async with self.session_factory() as session:
            stmt = select(InvoiceGood).where(InvoiceGood.deleted_at.is_(None))

            if name:
                stmt = stmt.where(InvoiceGood.name.ilike(f"%{name}%"))
            if category:
                stmt = stmt.where(InvoiceGood.category == category)
            if invoice_id:
                stmt = stmt.where(InvoiceGood.invoice_id == invoice_id)

            stmt = stmt.order_by(InvoiceGood.id.desc()).limit(limit).offset(offset)

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row.__dict__ for row in rows]

    async def list_categories(self) -> List[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(distinct(InvoiceGood.category)).where(
                    InvoiceGood.category.isnot(None),
                    InvoiceGood.deleted_at.is_(None),
                )
            )
            return [row[0] for row in result.all()]

    async def delete(self, record_id: int) -> bool:
        """Soft-delete an invoice good record"""
        async with self.session_factory() as session:
            result = await session.execute(
                update(InvoiceGood)
                .where(
                    InvoiceGood.id == record_id,
                    InvoiceGood.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.utcnow())
            )
            await session.commit()
            return result.rowcount > 0
