from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.domain.repositories.i_sales_invoice_repository import (
    ISalesInvoiceRepository,
)
from src.infrastructure.repositories.models import SalesInvoice
from src.infrastructure.repositories.repository_utils import (
    chunked,
    model_to_dict,
    to_decimal,
)


class SalesInvoiceRepository(ISalesInvoiceRepository):
    """Persistence operations for invoice-level facts."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session_factory() as session:
            invoice = SalesInvoice(
                invoice_id=data.get("invoice_id") or str(uuid4()),
                invoice_number=data["invoice_number"],
                issued_at=data["issued_at"],
                customer_id=data["customer_id"],
                customer_name_snapshot=data["customer_name_snapshot"],
                customer_address_detail_snapshot=data.get(
                    "customer_address_detail_snapshot"
                ),
                customer_village_name_snapshot=data.get(
                    "customer_village_name_snapshot"
                ),
                customer_ward_name_snapshot=data.get("customer_ward_name_snapshot"),
                invoice_total_amount=to_decimal(data["invoice_total_amount"]),
                debt_delta_amount=(
                    to_decimal(data["debt_delta_amount"])
                    if data.get("debt_delta_amount") is not None
                    else None
                ),
            )
            session.add(invoice)
            await session.commit()
            await session.refresh(invoice)
            return model_to_dict(invoice)

    async def get_by_id(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(SalesInvoice).where(
                    SalesInvoice.invoice_id == invoice_id,
                    SalesInvoice.deleted_at.is_(None),
                )
            )
            invoice = result.scalar_one_or_none()
            return model_to_dict(invoice) if invoice else None

    async def get_by_invoice_number(
        self, invoice_number: str
    ) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(SalesInvoice).where(
                    SalesInvoice.invoice_number == invoice_number,
                    SalesInvoice.deleted_at.is_(None),
                )
            )
            invoice = result.scalar_one_or_none()
            return model_to_dict(invoice) if invoice else None

    async def upsert_many(self, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        if not rows:
            return {}

        invoice_ids: Dict[str, str] = {}
        async with self.session_factory() as session:
            for batch in chunked(rows):
                values = [
                    {
                        **row,
                        "invoice_id": row.get("invoice_id") or str(uuid4()),
                        "invoice_total_amount": to_decimal(row["invoice_total_amount"]),
                        "debt_delta_amount": (
                            to_decimal(row["debt_delta_amount"])
                            if row.get("debt_delta_amount") is not None
                            else None
                        ),
                    }
                    for row in batch
                ]
                insert_stmt = pg_insert(SalesInvoice).values(values)
                stmt = insert_stmt.on_conflict_do_update(
                    index_elements=[SalesInvoice.invoice_number],
                    set_={
                        "issued_at": insert_stmt.excluded.issued_at,
                        "customer_id": insert_stmt.excluded.customer_id,
                        "customer_name_snapshot": (
                            insert_stmt.excluded.customer_name_snapshot
                        ),
                        "customer_address_detail_snapshot": (
                            insert_stmt.excluded.customer_address_detail_snapshot
                        ),
                        "customer_village_name_snapshot": (
                            insert_stmt.excluded.customer_village_name_snapshot
                        ),
                        "customer_ward_name_snapshot": (
                            insert_stmt.excluded.customer_ward_name_snapshot
                        ),
                        "invoice_total_amount": (
                            insert_stmt.excluded.invoice_total_amount
                        ),
                        "debt_delta_amount": (insert_stmt.excluded.debt_delta_amount),
                        "deleted_at": None,
                    },
                ).returning(
                    SalesInvoice.invoice_number,
                    SalesInvoice.invoice_id,
                )
                result = await session.execute(stmt)
                invoice_ids.update(dict(result.all()))
            await session.commit()
        return invoice_ids

    async def list(
        self,
        customer_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.session_factory() as session:
            stmt = select(SalesInvoice).where(SalesInvoice.deleted_at.is_(None))
            if customer_id:
                stmt = stmt.where(SalesInvoice.customer_id == customer_id)
            if customer_name:
                stmt = stmt.where(
                    SalesInvoice.customer_name_snapshot.ilike(f"%{customer_name}%")
                )
            if date_from:
                stmt = stmt.where(SalesInvoice.issued_at >= date_from)
            if date_to:
                stmt = stmt.where(SalesInvoice.issued_at <= date_to)

            stmt = (
                stmt.order_by(SalesInvoice.issued_at.desc()).limit(limit).offset(offset)
            )
            result = await session.execute(stmt)
            return [model_to_dict(row) for row in result.scalars().all()]

    async def delete(self, invoice_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(SalesInvoice)
                .where(
                    SalesInvoice.invoice_id == invoice_id,
                    SalesInvoice.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.utcnow())
            )
            await session.commit()
            return result.rowcount > 0
