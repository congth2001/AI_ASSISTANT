from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.domain.repositories.i_customer_repository import ICustomerRepository
from src.infrastructure.repositories.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesReturn,
)
from src.infrastructure.repositories.repository_utils import chunked, model_to_dict


class CustomerRepository(ICustomerRepository):
    """Persistence operations for canonical customer identities."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session_factory() as session:
            customer_data = {
                "customer_identity_key": data["customer_identity_key"],
                "customer_name": data["customer_name"],
                "address_detail": data.get("address_detail"),
                "village_name": data.get("village_name"),
                "ward_name": data.get("ward_name"),
            }
            if data.get("customer_id"):
                customer_data["customer_id"] = data["customer_id"]
            customer = Customer(**customer_data)

            session.add(customer)
            await session.commit()
            await session.refresh(customer)
            return model_to_dict(customer)

    async def get_by_id(self, customer_id: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Customer).where(
                    Customer.customer_id == customer_id,
                    Customer.deleted_at.is_(None),
                )
            )
            customer = result.scalar_one_or_none()
            return model_to_dict(customer) if customer else None

    async def get_by_identity_key(self, identity_key: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Customer).where(
                    Customer.customer_identity_key == identity_key,
                    Customer.deleted_at.is_(None),
                )
            )
            customer = result.scalar_one_or_none()
            return model_to_dict(customer) if customer else None

    async def upsert_many(self, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        if not rows:
            return {}

        customer_ids: Dict[str, str] = {}
        async with self.session_factory() as session:
            for batch in chunked(rows):
                insert_stmt = pg_insert(Customer).values(list(batch))
                stmt = insert_stmt.on_conflict_do_update(
                    constraint="uq_customers_customer_identity_key",
                    set_={
                        "customer_name": insert_stmt.excluded.customer_name,
                        "address_detail": insert_stmt.excluded.address_detail,
                        "village_name": insert_stmt.excluded.village_name,
                        "ward_name": insert_stmt.excluded.ward_name,
                        "updated_at": func.now(),
                        "deleted_at": None,
                    },
                ).returning(
                    Customer.customer_identity_key,
                    Customer.customer_id,
                )
                result = await session.execute(stmt)
                customer_ids.update(
                    {
                        identity_key: str(customer_id)
                        for identity_key, customer_id in result.all()
                    }
                )
            await session.commit()
        return customer_ids

    async def soft_delete_unreferenced(self) -> int:
        async with self.session_factory() as session:
            active_invoice = exists().where(
                SalesInvoice.customer_id == Customer.customer_id,
                SalesInvoice.deleted_at.is_(None),
            )
            active_debt = exists().where(
                CustomerDebtTransaction.customer_id == Customer.customer_id,
                CustomerDebtTransaction.deleted_at.is_(None),
            )
            active_return = exists().where(
                SalesReturn.customer_id == Customer.customer_id,
                SalesReturn.deleted_at.is_(None),
            )
            result = await session.execute(
                update(Customer)
                .where(
                    Customer.deleted_at.is_(None),
                    ~active_invoice,
                    ~active_debt,
                    ~active_return,
                )
                .values(deleted_at=func.now(), updated_at=func.now())
            )
            await session.commit()
            return result.rowcount

    async def list(
        self,
        name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with self.session_factory() as session:
            stmt = select(Customer).where(Customer.deleted_at.is_(None))
            if name:
                stmt = stmt.where(Customer.customer_name.ilike(f"%{name}%"))

            stmt = (
                stmt.order_by(Customer.customer_name.asc()).limit(limit).offset(offset)
            )
            result = await session.execute(stmt)
            return [model_to_dict(row) for row in result.scalars().all()]

    async def delete(self, customer_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(Customer)
                .where(
                    Customer.customer_id == customer_id,
                    Customer.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return result.rowcount > 0
