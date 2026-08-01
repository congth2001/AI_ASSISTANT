from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.domain.repositories.i_sales_invoice_line_repository import (
    ISalesInvoiceLineRepository,
)
from src.infrastructure.repositories.models import SalesInvoiceLine
from src.infrastructure.repositories.repository_utils import (
    chunked,
    model_to_dict,
    to_decimal,
)


class SalesInvoiceLineRepository(ISalesInvoiceLineRepository):
    """Persistence operations for invoice line-level facts."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session_factory() as session:
            line = SalesInvoiceLine(
                invoice_line_id=data.get("invoice_line_id") or str(uuid4()),
                invoice_id=data["invoice_id"],
                line_number=data["line_number"],
                product_name=data["product_name"],
                product_category_name=data.get("product_category_name"),
                unit_name=data["unit_name"],
                unit_price=to_decimal(data["unit_price"]),
                quantity=to_decimal(data["quantity"]),
                line_amount=to_decimal(data["line_amount"]),
            )
            session.add(line)
            await session.commit()
            await session.refresh(line)
            return model_to_dict(line)

    async def get_by_id(self, invoice_line_id: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(SalesInvoiceLine).where(
                    SalesInvoiceLine.invoice_line_id == invoice_line_id,
                    SalesInvoiceLine.deleted_at.is_(None),
                )
            )
            line = result.scalar_one_or_none()
            return model_to_dict(line) if line else None

    async def get_by_invoice_id(self, invoice_id: str) -> List[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(SalesInvoiceLine)
                .where(
                    SalesInvoiceLine.invoice_id == invoice_id,
                    SalesInvoiceLine.deleted_at.is_(None),
                )
                .order_by(SalesInvoiceLine.line_number.asc())
            )
            return [model_to_dict(row) for row in result.scalars().all()]

    async def upsert_snapshot(
        self,
        rows: List[Dict[str, Any]],
        invoice_ids: List[str],
    ) -> int:
        if not invoice_ids:
            return 0

        async with self.session_factory() as session:
            for invoice_id_batch in chunked(invoice_ids):
                await session.execute(
                    update(SalesInvoiceLine)
                    .where(
                        SalesInvoiceLine.invoice_id.in_(invoice_id_batch),
                        SalesInvoiceLine.deleted_at.is_(None),
                    )
                    .values(deleted_at=func.now())
                )

            for batch in chunked(rows):
                values = [
                    {
                        **row,
                        "invoice_line_id": row.get("invoice_line_id") or str(uuid4()),
                        "unit_price": to_decimal(row["unit_price"]),
                        "quantity": to_decimal(row["quantity"]),
                        "line_amount": to_decimal(row["line_amount"]),
                    }
                    for row in batch
                ]
                insert_stmt = pg_insert(SalesInvoiceLine).values(values)
                stmt = insert_stmt.on_conflict_do_update(
                    constraint="uq_sales_invoice_lines_invoice_line",
                    set_={
                        "product_name": insert_stmt.excluded.product_name,
                        "product_category_name": (
                            insert_stmt.excluded.product_category_name
                        ),
                        "unit_name": insert_stmt.excluded.unit_name,
                        "unit_price": insert_stmt.excluded.unit_price,
                        "quantity": insert_stmt.excluded.quantity,
                        "line_amount": insert_stmt.excluded.line_amount,
                        "deleted_at": None,
                    },
                )
                await session.execute(stmt)

            await session.commit()
        return len(rows)

    async def list(
        self,
        product_name: Optional[str] = None,
        category_name: Optional[str] = None,
        invoice_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.session_factory() as session:
            stmt = select(SalesInvoiceLine).where(SalesInvoiceLine.deleted_at.is_(None))
            if product_name:
                stmt = stmt.where(
                    SalesInvoiceLine.product_name.ilike(f"%{product_name}%")
                )
            if category_name:
                stmt = stmt.where(
                    SalesInvoiceLine.product_category_name == category_name
                )
            if invoice_id:
                stmt = stmt.where(SalesInvoiceLine.invoice_id == invoice_id)

            stmt = (
                stmt.order_by(
                    SalesInvoiceLine.invoice_id.desc(),
                    SalesInvoiceLine.line_number.asc(),
                )
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [model_to_dict(row) for row in result.scalars().all()]

    async def list_categories(self) -> List[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(distinct(SalesInvoiceLine.product_category_name)).where(
                    SalesInvoiceLine.product_category_name.isnot(None),
                    SalesInvoiceLine.deleted_at.is_(None),
                )
            )
            return [row[0] for row in result.all()]

    async def delete(self, invoice_line_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(SalesInvoiceLine)
                .where(
                    SalesInvoiceLine.invoice_line_id == invoice_line_id,
                    SalesInvoiceLine.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.utcnow())
            )
            await session.commit()
            return result.rowcount > 0
